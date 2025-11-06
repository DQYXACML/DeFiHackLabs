#!/usr/bin/env python3
"""
攻击状态收集工具 - 支持完整的动态数据类型收集

功能：
1. 从exp文件提取fork信息（网络和区块号）和攻击交易哈希
2. 使用web3.py收集攻击发生前的完整链上状态
3. 支持两种收集模式：
   - Trace模式: 使用debug_traceTransaction获取攻击交易访问的所有storage slots
             包括mappings和动态数组（需要RPC支持debug API）
   - Sequential模式: 顺序扫描slot 0-N（仅能获取简单变量）
4. 保存完整状态到JSON文件

收集方法对比：
┌──────────────┬──────────────────┬────────────────────┐
│   方法        │  可获取数据类型   │     准确性          │
├──────────────┼──────────────────┼────────────────────┤
│ Trace        │ 简单变量         │  完整捕获          │
│              │ + Mappings       │  (攻击实际访问的    │
│              │ + 动态数组       │   所有storage slots)│
├──────────────┼──────────────────┼────────────────────┤
│ Sequential   │ 仅简单变量       │  不完整            │
│              │ (slot 0-99)      │  (~0.00001%的slots)│
└──────────────┴──────────────────┴────────────────────┘

使用示例：
    # 默认模式：优先trace，失败降级到sequential
    python src/test/collect_attack_states.py --filter 2024-01

    # 仅使用trace（失败则跳过）
    python src/test/collect_attack_states.py --trace-only

    # 强制使用sequential（禁用trace）
    python src/test/collect_attack_states.py --no-trace

作者: Claude Code
版本: 2.0.0 (支持trace-based完整收集)
"""

import re
import json
import os
import sys
import time
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from datetime import datetime
from dataclasses import dataclass, asdict
from collections import defaultdict

try:
    from web3 import Web3
    from web3.exceptions import Web3Exception
except ImportError:
    print("错误：需要安装web3库")
    print("请运行: pip install web3")
    sys.exit(1)

POA_MIDDLEWARE = None

try:
    from web3.middleware import geth_poa_middleware as _poa_middleware
    POA_MIDDLEWARE = _poa_middleware
except ImportError:
    try:
        from web3.middleware import ExtraDataToPOAMiddleware as _poa_middleware
        POA_MIDDLEWARE = _poa_middleware
    except ImportError:
        try:
            # 兼容旧版web3路径
            from web3.middleware.geth_poa import geth_poa_middleware as _poa_middleware
            POA_MIDDLEWARE = _poa_middleware
        except ImportError:
            POA_MIDDLEWARE = None

try:
    import toml
except ImportError:
    print("错误：需要安装toml库")
    print("请运行: pip install toml")
    sys.exit(1)

# ============================================================================
# 配置
# ============================================================================

# 日志配置
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# 路径配置
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
EXTRACTED_DIR = PROJECT_ROOT / 'extracted_contracts'
TEST_DIR = PROJECT_ROOT / 'src' / 'test'
FOUNDRY_TOML = PROJECT_ROOT / 'foundry.toml'

# 收集配置
DEFAULT_STORAGE_DEPTH = 100  # 扫描storage的深度
RPC_TIMEOUT = 30  # RPC超时（秒）
RPC_RETRY_TIMES = 3  # 重试次数
RPC_RETRY_DELAY = 2  # 重试延迟（秒）
REQUEST_DELAY = 0.1  # 请求间隔，避免rate limit

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ForkInfo:
    """Fork配置信息"""
    chain: str
    block_number: int
    original_expression: str
    source_file: str

@dataclass
class AddressInfo:
    """地址信息（从addresses.json读取）"""
    address: str
    name: Optional[str] = None
    chain: Optional[str] = None
    source: str = "unknown"
    context: Optional[str] = None  # 提取上下文信息

@dataclass
class StateSnapshot:
    """状态快照"""
    balance_wei: str
    balance_eth: str
    nonce: int
    code: str
    code_size: int
    is_contract: bool
    storage: Dict[str, str]
    erc20_balances: Dict[str, str]

@dataclass
class CollectionStats:
    """收集统计"""
    total_events: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

class TraceUnsupportedError(Exception):
    """指示当前RPC不支持trace或未返回预期数据"""
    pass
# ============================================================================
# RPC配置加载
# ============================================================================

class RPCManager:
    """RPC端点管理器"""

    POA_CHAINS = {'bsc'}

    def __init__(self, foundry_toml_path: Path):
        self.logger = logging.getLogger(__name__ + '.RPCManager')
        self.web3_instances: Dict[str, Web3] = {}
        self.rpc_endpoints = self._load_rpc_endpoints(foundry_toml_path)
        self.poa_configured: Set[str] = set()

    def _load_rpc_endpoints(self, toml_path: Path) -> Dict[str, str]:
        """从foundry.toml加载RPC端点"""
        try:
            with open(toml_path, 'r') as f:
                config = toml.load(f)

            endpoints = config.get('rpc_endpoints', {})
            self.logger.info(f"加载了 {len(endpoints)} 个RPC端点")
            return endpoints

        except Exception as e:
            self.logger.error(f"加载foundry.toml失败: {e}")
            return {}

    def get_web3(self, chain: str) -> Optional[Web3]:
        """获取Web3实例（带缓存）"""
        if chain in self.web3_instances:
            return self.web3_instances[chain]

        if chain not in self.rpc_endpoints:
            self.logger.error(f"未找到链 {chain} 的RPC端点")
            return None

        try:
            rpc_url = self.rpc_endpoints[chain]
            # 支持HTTP和WebSocket
            if rpc_url.startswith('ws'):
                from web3 import WebsocketProvider
                provider = WebsocketProvider(rpc_url)
            else:
                from web3 import HTTPProvider
                provider = HTTPProvider(rpc_url, request_kwargs={'timeout': RPC_TIMEOUT})

            w3 = Web3(provider)

            # 测试连接
            if not w3.is_connected():
                self.logger.error(f"无法连接到 {chain} 的RPC端点: {rpc_url}")
                return None

            self._configure_middlewares(chain, w3)

            self.logger.info(f"✓ 已连接到 {chain}: {rpc_url[:50]}...")
            self.web3_instances[chain] = w3
            return w3

        except Exception as e:
            self.logger.error(f"创建Web3实例失败 ({chain}): {e}")
            return None

    def _configure_middlewares(self, chain: str, w3: Web3) -> None:
        """针对特定链配置必要的中间件（如PoA处理）"""
        chain_key = chain.lower()

        if chain_key in self.POA_CHAINS:
            self._inject_geth_poa(chain, w3, "已知PoA链")

        try:
            w3.eth.get_block('latest')
        except ValueError as err:
            if "The field extraData is" in str(err):
                if self._inject_geth_poa(chain, w3, "检测到PoA区块头"):
                    try:
                        w3.eth.get_block('latest')
                    except Exception as retry_err:
                        self.logger.debug(f"{chain}: 注入PoA中间件后测试区块失败: {retry_err}")
            else:
                self.logger.debug(f"{chain}: 获取latest区块时出现非PoA错误: {err}")
        except Exception as err:
            self.logger.debug(f"{chain}: 初始化时获取区块失败: {err}")

    def _inject_geth_poa(self, chain: str, w3: Web3, reason: str) -> bool:
        """注入geth_poa_middleware，避免PoA链extraData长度问题"""
        chain_key = chain.lower()

        if chain_key in self.poa_configured:
            self.logger.debug(f"{chain}: 已注入PoA中间件，跳过重复操作")
            return True

        if POA_MIDDLEWARE is None:
            self.logger.error(
                f"{chain}: 当前web3版本缺少PoA中间件，请安装包含 geth_poa_middleware 或 ExtraDataToPOAMiddleware 的 web3 版本（例如 pip install 'web3>=5.31'）。"
            )
            return False

        middleware_name = getattr(POA_MIDDLEWARE, '__name__', 'PoA middleware')
        self.logger.info(f"{chain}: {reason}，注入{middleware_name}")
        try:
            w3.middleware_onion.inject(POA_MIDDLEWARE, layer=0)
        except ValueError:
            # 已存在则忽略
            pass

        self.poa_configured.add(chain_key)
        return True

# ============================================================================
# Fork信息提取
# ============================================================================

class ForkExtractor:
    """从exp文件提取fork信息"""

    # 匹配createSelectFork或createFork
    FORK_PATTERN = re.compile(
        r'(?:vm|cheats)\.(?:createSelectFork|createFork)\s*\(\s*["\'](\w+)["\']\s*,\s*([^)]+)\)',
        re.MULTILINE
    )

    # 匹配变量赋值，如: uint256 blocknumToForkFrom = 35123711;
    VAR_ASSIGN_PATTERN = re.compile(
        r'(?:uint256|uint|int)\s+(\w+)\s*=\s*([0-9_]+)\s*;'
    )

    # 匹配攻击交易哈希注释
    # 支持格式：
    #   // Attack Tx : 0x123...
    #   // Attack Transaction: https://arbiscan.io/tx/0x123...
    #   // Attack Tx : https://etherscan.io/tx/0x123...
    #   // Attack Tx : https://app.blocksec.com/explorer/tx/eth/0x123...
    ATTACK_TX_PATTERN = re.compile(
        r'Attack\s+(?:Tx|Transaction)\s*:.*?(0x[a-fA-F0-9]{64})',
        re.MULTILINE | re.IGNORECASE
    )

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.ForkExtractor')

    def extract_fork_info(self, exp_file: Path) -> Optional[ForkInfo]:
        """
        提取fork信息

        Returns:
            ForkInfo或None（如果提取失败）
        """
        try:
            with open(exp_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.logger.error(f"读取文件失败 {exp_file}: {e}")
            return None

        # 查找fork调用
        match = self.FORK_PATTERN.search(content)
        if not match:
            self.logger.warning(f"未找到fork配置: {exp_file.name}")
            return None

        chain = match.group(1)
        block_expr = match.group(2).strip()

        # 解析区块号表达式
        block_number = self._parse_block_expression(block_expr, content)

        if block_number is None:
            self.logger.error(f"无法解析区块号: {block_expr}")
            return None

        # createSelectFork里的区块号就是要fork的状态，直接使用
        return ForkInfo(
            chain=chain,
            block_number=block_number,
            original_expression=block_expr,
            source_file=str(exp_file)
        )

    def _parse_block_expression(self, expr: str, content: str, depth: int = 0) -> Optional[int]:
        """解析区块号表达式"""

        if depth > 5:
            self.logger.warning(f"区块号表达式解析递归过深: {expr}")
            return None

        expr = expr.strip()

        # 情况1: 纯数字（允许下划线格式）
        if re.fullmatch(r'\d[\d_]*', expr):
            return int(expr.replace('_', ''))

        # 情况2: 简单算术（仅处理加减法）
        simple_expr = expr.replace('_', '')
        if re.fullmatch(r'[\d\s\+\-\(\)]+', simple_expr):
            try:
                value = eval(simple_expr, {"__builtins__": None}, {})
                if isinstance(value, int):
                    return value
            except Exception:
                pass

        # 情况3: 变量引用（支持下划线/大小写/修饰符）
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', expr):
            var_pattern = re.compile(
                rf'(?:uint256|uint|int)\s+(?:\w+\s+)*{re.escape(expr)}\s*=\s*([^;]+);'
            )
            var_match = var_pattern.search(content)
            if var_match:
                value_expr = var_match.group(1).strip()
                return self._parse_block_expression(value_expr, content, depth + 1)

            self.logger.warning(f"未找到变量 {expr} 的定义")
            return None

        # 其他情况
        self.logger.warning(f"不支持的区块号表达式: {expr}")
        return None

    def extract_attack_tx_hash(self, exp_file: Path) -> Optional[str]:
        """
        从exp文件提取攻击交易哈希

        查找类似的注释:
        // Attack Tx : https://etherscan.io/tx/0x123...
        // Attack Tx : 0x123...

        Returns:
            交易哈希（不含0x前缀的URL）或None
        """
        try:
            with open(exp_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.logger.error(f"读取文件失败 {exp_file}: {e}")
            return None

        # 查找攻击交易注释
        match = self.ATTACK_TX_PATTERN.search(content)
        if not match:
            self.logger.debug(f"未找到攻击交易哈希: {exp_file.name}")
            return None

        # 提取哈希（group(1)是交易哈希）
        tx_hash = match.group(1)

        # 验证格式
        if not tx_hash.startswith('0x') or len(tx_hash) != 66:
            self.logger.warning(f"无效的交易哈希格式: {tx_hash}")
            return None

        self.logger.debug(f"提取到攻击交易: {tx_hash[:16]}...")
        return tx_hash

# ============================================================================
# 状态收集器
# ============================================================================

class StateCollector:
    """链上状态收集器"""

    # ERC20 balanceOf selector
    BALANCE_OF_SELECTOR = '0x70a08231'

    def __init__(self, rpc_manager: RPCManager, storage_depth: int = DEFAULT_STORAGE_DEPTH,
                 use_trace: bool = True, trace_only: bool = False):
        self.rpc_manager = rpc_manager
        self.storage_depth = storage_depth
        self.use_trace = use_trace
        self.trace_only = trace_only
        self.logger = logging.getLogger(__name__ + '.StateCollector')
        # Keep track of chains whose RPC endpoints do not support trace APIs to avoid repeated failures
        self.unsupported_trace_chains: Set[str] = set()

    def collect_state(self, chain: str, block_number: int,
                     addresses: List[AddressInfo], attack_tx_hash: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        收集指定区块的状态

        Args:
            chain: 链名称
            block_number: 区块号
            addresses: 地址列表
            attack_tx_hash: 攻击交易哈希（用于trace-based收集）

        Returns:
            状态字典或None（如果失败）
        """
        w3 = self.rpc_manager.get_web3(chain)
        if not w3:
            return None

        self.logger.info(f"  收集区块 {block_number} 的状态（{len(addresses)} 个地址）")
        if attack_tx_hash:
            self.logger.info(f"  使用攻击交易: {attack_tx_hash[:16]}...")

        try:
            # 获取区块信息
            block = self._retry_call(lambda: w3.eth.get_block(block_number))
            if not block:
                self.logger.error(f"无法获取区块 {block_number}")
                return None

            # 收集每个地址的状态
            address_states = {}
            for i, addr_info in enumerate(addresses, 1):
                self.logger.debug(f"    [{i}/{len(addresses)}] {addr_info.address}")
                state = self._collect_address_state(chain, w3, addr_info.address, block_number, attack_tx_hash)
                if state:
                    state_dict = asdict(state)
                    state_dict['name'] = addr_info.name or 'Unknown'
                    address_states[addr_info.address] = state_dict

                # 添加延迟避免rate limit
                time.sleep(REQUEST_DELAY)

            # 递归收集存储槽中的合约地址
            self.logger.info(f"  扫描存储槽中的合约地址...")
            discovered_addresses = self._discover_addresses_from_storage(w3, address_states, block_number, attack_tx_hash)
            if discovered_addresses:
                self.logger.info(f"  发现 {len(discovered_addresses)} 个额外的合约地址")
                for discovered_addr in discovered_addresses:
                    self.logger.debug(f"    收集: {discovered_addr}")
                    state = self._collect_address_state(chain, w3, discovered_addr, block_number, attack_tx_hash)
                    if state:
                        state_dict = asdict(state)
                        state_dict['name'] = 'Discovered from storage'
                        address_states[discovered_addr] = state_dict
                    time.sleep(REQUEST_DELAY)

            # 构建完整状态
            collection_method = 'trace'
            if not (attack_tx_hash and self.use_trace and chain.lower() not in self.unsupported_trace_chains):
                collection_method = 'sequential'

            return {
                'metadata': {
                    'chain': chain,
                    'block_number': block_number,
                    'timestamp': block['timestamp'],
                    'block_hash': block['hash'].hex(),
                    'collected_at': datetime.now().isoformat(),
                    'total_addresses': len(addresses),
                    'collected_addresses': len(address_states),
                    'collection_method': collection_method,
                    'attack_tx_hash': attack_tx_hash if attack_tx_hash else None
                },
                'addresses': address_states
            }

        except Exception as e:
            self.logger.error(f"收集状态失败: {e}")
            return None

    def _collect_address_state(self, chain: str, w3: Web3, address: str,
                              block_number: int, attack_tx_hash: Optional[str] = None) -> Optional[StateSnapshot]:
        """收集单个地址的状态"""
        try:
            # 标准化地址
            address = Web3.to_checksum_address(address)

            # 基础数据
            balance = self._retry_call(lambda: w3.eth.get_balance(address, block_number))
            nonce = self._retry_call(lambda: w3.eth.get_transaction_count(address, block_number))
            code = self._retry_call(lambda: w3.eth.get_code(address, block_number))

            if balance is None or nonce is None or code is None:
                return None

            is_contract = len(code) > 0

            # 存储数据（只对合约收集）
            storage = {}
            if is_contract:
                storage = self._collect_storage(chain, w3, address, block_number, attack_tx_hash)

            # ERC20余额（只对合约收集）
            erc20_balances = {}
            # 暂时留空，后续可以扩展

            return StateSnapshot(
                balance_wei=str(balance),
                balance_eth=str(w3.from_wei(balance, 'ether')),
                nonce=nonce,
                code=code.hex(),
                code_size=len(code),
                is_contract=is_contract,
                storage=storage,
                erc20_balances=erc20_balances
            )

        except Exception as e:
            self.logger.warning(f"收集地址 {address} 状态失败: {e}")
            return None

    def _collect_storage(self, chain: str, w3: Web3, address: str, block_number: int,
                        attack_tx_hash: Optional[str] = None) -> Dict[str, str]:
        """
        收集合约存储（支持trace和sequential两种模式）

        Args:
            w3: Web3实例
            address: 合约地址
            block_number: 区块号
            attack_tx_hash: 攻击交易哈希（可选，用于trace方法）

        Returns:
            存储字典 {slot: value}
        """
        storage = {}

        # 方法1: 优先尝试trace-based收集（如果启用且有tx_hash）
        chain_key = chain.lower()

        if attack_tx_hash and self.use_trace and chain_key not in self.unsupported_trace_chains:
            try:
                self.logger.debug(f"      → 尝试trace方法收集存储")
                storage = self._collect_storage_from_trace(chain, w3, address, attack_tx_hash, block_number)
                if storage:
                    self.logger.info(f"      ✓ Trace方法成功: 获取 {len(storage)} 个slots")
                    return storage
                else:
                    self.logger.warning(f"      ⚠ Trace方法返回空数据")

            except TraceUnsupportedError as e:
                self.logger.warning(f"      ⚠ Trace方法不可用: {e}")
                self.unsupported_trace_chains.add(chain_key)
                if self.trace_only:
                    self.logger.error(f"      ✗ trace-only模式下失败，跳过sequential扫描")
                    return {}
            except Exception as e:
                self.logger.warning(f"      ⚠ Trace方法失败: {e}")
                if self.trace_only:
                    self.logger.error(f"      ✗ trace-only模式下失败，跳过sequential扫描")
                    return {}
        elif attack_tx_hash and self.use_trace and chain_key in self.unsupported_trace_chains:
            self.logger.debug(f"      Trace已对 {chain} 禁用，改用sequential扫描")

        # 方法2: 降级到sequential扫描
        if not self.trace_only:
            self.logger.debug(f"      → 使用sequential扫描")
            storage = self._sequential_scan(w3, address, block_number)
            self.logger.debug(f"      Sequential方法: 获取 {len(storage)} 个slots")

        return storage

    def _collect_storage_from_trace(self, chain: str, w3: Web3, address: str,
                                    tx_hash: str, block_number: int) -> Dict[str, str]:
        """
        使用交易trace收集完整存储（包括mappings和动态数组）

        使用debug_traceTransaction的prestateTracer来获取交易访问的所有storage slots

        Args:
            w3: Web3实例
            address: 合约地址
            tx_hash: 交易哈希
            block_number: 区块号

        Returns:
            存储字典 {slot: value}
        """
        storage = {}

        try:
            # 标准化地址（小写，用于匹配trace结果）
            address_lower = address.lower()

            # 调用debug_traceTransaction with prestateTracer
            # prestateTracer返回交易执行前所有被访问地址的状态
            trace_result = w3.provider.make_request(
                'debug_traceTransaction',
                [tx_hash, {'tracer': 'prestateTracer'}]
            )

            if not isinstance(trace_result, dict):
                raise TraceUnsupportedError(f"返回格式异常: {type(trace_result)}")

            if 'error' in trace_result:
                raise TraceUnsupportedError(f"RPC错误: {trace_result['error']}")

            prestate = trace_result.get('result')
            if prestate is None:
                # 某些实现可能直接返回prestate字段
                for key in ('prestate', 'state', 'states'):
                    if key in trace_result:
                        prestate = trace_result[key]
                        break

            if prestate is None:
                keys_preview = list(trace_result.keys())
                raise TraceUnsupportedError(f"未返回prestate数据(keys={keys_preview})")

            if not isinstance(prestate, dict):
                raise TraceUnsupportedError(f"prestate类型异常: {type(prestate)}")

            # 查找目标地址的prestate
            # prestateTracer返回的地址可能是小写或校验和格式
            address_data = None
            for addr in prestate:
                if addr.lower() == address_lower:
                    address_data = prestate[addr]
                    break

            if not address_data:
                self.logger.debug(f"      Trace中未找到地址 {address}（交易可能未访问此合约）")
                return storage

            # 提取storage数据
            if 'storage' in address_data:
                touched_storage = address_data['storage']
                self.logger.debug(f"      Trace发现 {len(touched_storage)} 个被访问的slots")

                # prestateTracer返回的是交易前的状态
                # 我们需要读取这些slots在指定区块的值
                for slot_hex, _ in touched_storage.items():
                    try:
                        # 将slot转换为整数（处理0x前缀）
                        if slot_hex.startswith('0x'):
                            slot_int = int(slot_hex, 16)
                        else:
                            slot_int = int(slot_hex, 16)

                        # 读取该slot在目标区块的值
                        value = self._retry_call(
                            lambda: w3.eth.get_storage_at(address, slot_int, block_number)
                        )

                        # 只保存非零值
                        if value and value != b'\x00' * 32:
                            # 使用十进制slot作为key（保持一致性）
                            storage[str(slot_int)] = value.hex()

                    except Exception as e:
                        self.logger.debug(f"      读取slot {slot_hex} 失败: {e}")
                        continue

            else:
                self.logger.debug(f"      Trace结果中没有storage字段")

            return storage

        except Exception as e:
            # 捕获所有异常并重新抛出，让上层决定是否降级
            raise Exception(f"debug_traceTransaction失败: {e}")

    def _sequential_scan(self, w3: Web3, address: str, block_number: int) -> Dict[str, str]:
        """
        顺序扫描存储槽（传统方法，仅能获取简单变量）

        Args:
            w3: Web3实例
            address: 合约地址
            block_number: 区块号

        Returns:
            存储字典 {slot: value}
        """
        storage = {}

        for slot in range(self.storage_depth):
            try:
                value = self._retry_call(
                    lambda: w3.eth.get_storage_at(address, slot, block_number)
                )
                if value and value != b'\x00' * 32:
                    storage[str(slot)] = value.hex()

            except Exception as e:
                self.logger.debug(f"读取slot {slot} 失败: {e}")
                break  # 遇到错误停止扫描

        return storage

    def _discover_addresses_from_storage(self, w3: Web3, address_states: Dict[str, Dict],
                                         block_number: int, attack_tx_hash: Optional[str] = None) -> List[str]:
        """
        从已收集的存储槽中发现新的合约地址

        Args:
            w3: Web3实例
            address_states: 已收集的地址状态字典
            block_number: 区块号
            attack_tx_hash: 攻击交易哈希（可选）

        Returns:
            发现的新合约地址列表
        """
        discovered = set()
        existing_addresses = set(addr.lower() for addr in address_states.keys())

        for addr, state in address_states.items():
            if not state.get('storage'):
                continue

            # 扫描每个存储槽的值
            for slot, value in state['storage'].items():
                # 标准化值格式（可能有或没有 0x 前缀）
                if value.startswith('0x'):
                    hex_value = value
                else:
                    hex_value = '0x' + value

                # 检查是否是地址格式（32字节，前12字节为0）
                if len(hex_value) == 66 and hex_value.startswith('0x000000000000000000000000'):
                    # 提取地址部分（最后20字节）
                    potential_addr = '0x' + hex_value[-40:]

                    # 跳过零地址和已知地址
                    if potential_addr == '0x' + '0' * 40:
                        continue
                    if potential_addr.lower() in existing_addresses:
                        continue
                    if potential_addr.lower() in discovered:
                        continue

                    # 检查是否是合约
                    try:
                        checksum_addr = Web3.to_checksum_address(potential_addr)
                        code = self._retry_call(lambda: w3.eth.get_code(checksum_addr, block_number))

                        if code and len(code) > 0:
                            self.logger.debug(f"      发现合约地址: {checksum_addr} (from {addr} slot {slot})")
                            discovered.add(checksum_addr)

                    except Exception as e:
                        self.logger.debug(f"      检查地址 {potential_addr} 失败: {e}")
                        continue

        return list(discovered)

    def _retry_call(self, func, max_retries: int = RPC_RETRY_TIMES):
        """带重试的RPC调用"""
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                if attempt < max_retries - 1:
                    self.logger.debug(f"RPC调用失败，重试 {attempt + 1}/{max_retries}: {e}")
                    time.sleep(RPC_RETRY_DELAY)
                else:
                    raise

# ============================================================================
# 主控制器
# ============================================================================

class AttackStateCollector:
    """攻击状态收集主控制器"""

    def __init__(self, rpc_manager: RPCManager, storage_depth: int = DEFAULT_STORAGE_DEPTH,
                 use_trace: bool = True, trace_only: bool = False):
        self.rpc_manager = rpc_manager
        self.fork_extractor = ForkExtractor()
        self.state_collector = StateCollector(rpc_manager, storage_depth, use_trace, trace_only)
        self.stats = CollectionStats()
        self.logger = logging.getLogger(__name__ + '.AttackStateCollector')

        # 错误日志文件
        self.error_log = TEST_DIR / 'collection_errors.log'

    def collect_all(self, date_filters: Optional[List[str]] = None,
                   skip_existing: bool = False, limit: Optional[int] = None):
        """
        收集所有攻击事件的状态

        Args:
            date_filters: 日期过滤器列表，如 ["2024-01"]
            skip_existing: 跳过已有state文件（默认True，使用--force时为False）
            limit: 限制处理数量（用于测试）
        """
        self.logger.info("=" * 80)
        self.logger.info("开始收集攻击状态")
        self.logger.info("=" * 80)

        # 查找所有事件
        events = self._find_all_events(date_filters)
        self.stats.total_events = len(events)

        if limit:
            events = events[:limit]
            self.logger.info(f"限制处理前 {limit} 个事件")

        self.logger.info(f"找到 {len(events)} 个攻击事件")

        # 处理每个事件
        for i, (month, event_name, event_dir) in enumerate(events, 1):
            self.logger.info(f"\n[{i}/{len(events)}] 处理: {month}/{event_name}")

            # 检查是否已存在
            state_file = event_dir / 'attack_state.json'
            if skip_existing and state_file.exists():
                self.logger.info("  ⊙ 已存在，跳过（使用 --force 可重新收集）")
                self.stats.skipped += 1
                continue

            try:
                success = self._process_event(month, event_name, event_dir)
                if success:
                    self.stats.successful += 1
                    self.logger.info("  ✓ 成功")
                else:
                    self.stats.failed += 1
                    self.logger.warning("  ✗ 失败")

            except Exception as e:
                error_msg = f"处理事件失败 {month}/{event_name}: {e}"
                self.logger.error(f"  ✗ {e}")
                self.stats.errors.append(error_msg)
                self.stats.failed += 1
                self._log_error(error_msg)

        # 打印统计
        self._print_summary()

    def _find_all_events(self, date_filters: Optional[List[str]] = None) -> List[Tuple[str, str, Path]]:
        """查找所有事件目录"""
        events = []

        if not EXTRACTED_DIR.exists():
            self.logger.error(f"提取目录不存在: {EXTRACTED_DIR}")
            return events

        # 遍历月份目录
        for month_dir in sorted(EXTRACTED_DIR.iterdir()):
            if not month_dir.is_dir():
                continue

            # 匹配 YYYY-MM 格式
            if not re.match(r'\d{4}-\d{2}', month_dir.name):
                continue

            # 应用过滤器
            if date_filters and not any(month_dir.name.startswith(f) for f in date_filters):
                continue

            # 遍历事件目录
            for event_dir in sorted(month_dir.iterdir()):
                if not event_dir.is_dir():
                    continue

                events.append((month_dir.name, event_dir.name, event_dir))

        return events

    def _process_event(self, month: str, event_name: str, event_dir: Path) -> bool:
        """
        处理单个事件

        Returns:
            是否成功
        """
        # 1. 查找对应的exp文件
        exp_file = TEST_DIR / month / f"{event_name}.sol"
        if not exp_file.exists():
            self.logger.warning(f"  未找到exp文件: {exp_file}")
            return False

        # 2. 提取fork信息
        fork_info = self.fork_extractor.extract_fork_info(exp_file)
        if not fork_info:
            self.logger.warning("  无法提取fork信息")
            return False

        self.logger.info(f"  Fork: {fork_info.chain} @ {fork_info.block_number}")

        # 3. 提取攻击交易哈希（用于trace-based收集）
        attack_tx_hash = self.fork_extractor.extract_attack_tx_hash(exp_file)
        if attack_tx_hash:
            self.logger.info(f"  攻击交易: {attack_tx_hash[:16]}...")
        else:
            self.logger.debug("  未找到攻击交易哈希（将使用sequential扫描）")

        # 4. 加载地址列表
        addresses_file = event_dir / 'addresses.json'
        if not addresses_file.exists():
            self.logger.warning(f"  未找到addresses.json")
            return False

        try:
            with open(addresses_file, 'r') as f:
                addresses_data = json.load(f)

            addresses = [AddressInfo(**addr) for addr in addresses_data]
            self.logger.info(f"  加载了 {len(addresses)} 个地址")

        except Exception as e:
            self.logger.error(f"  加载addresses.json失败: {e}")
            return False

        # 5. 收集状态（传递attack_tx_hash）
        state = self.state_collector.collect_state(
            fork_info.chain,
            fork_info.block_number,
            addresses,
            attack_tx_hash  # 新增：传递攻击交易哈希
        )

        if not state:
            self.logger.error("  状态收集失败")
            return False

        # 6. 保存状态
        state_file = event_dir / 'attack_state.json'
        try:
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)

            self.logger.debug(f"  保存到: {state_file}")
            return True

        except Exception as e:
            self.logger.error(f"  保存状态失败: {e}")
            return False

    def _log_error(self, message: str):
        """记录错误到日志文件"""
        with open(self.error_log, 'a', encoding='utf-8') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"{timestamp} - {message}\n")

    def _print_summary(self):
        """打印统计摘要"""
        self.logger.info("\n" + "=" * 80)
        self.logger.info("执行摘要")
        self.logger.info("=" * 80)
        self.logger.info(f"总事件数:        {self.stats.total_events}")
        self.logger.info(f"成功:            {self.stats.successful}")
        self.logger.info(f"失败:            {self.stats.failed}")
        self.logger.info(f"跳过:            {self.stats.skipped}")

        if self.stats.errors:
            self.logger.info(f"错误数:          {len(self.stats.errors)}")
            self.logger.info(f"错误日志:        {self.error_log}")

        self.logger.info("=" * 80)

# ============================================================================
# 命令行接口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='DeFi攻击状态收集工具 - 支持trace-based完整状态收集',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 收集所有事件（默认使用trace方法）
  python src/test/collect_attack_states.py

  # 只处理特定月份
  python src/test/collect_attack_states.py --filter 2024-01

  # 强制使用sequential扫描（不用trace）
  python src/test/collect_attack_states.py --no-trace

  # 仅使用trace方法，失败则跳过
  python src/test/collect_attack_states.py --trace-only

  # 强制覆盖已有attack_state.json
  python src/test/collect_attack_states.py --force

  # 测试模式（只处理5个）
  python src/test/collect_attack_states.py --limit 5 --debug

方法说明:
  - trace方法: 使用debug_traceTransaction获取攻击交易访问的所有storage slots
              包括mappings和动态数组（需要RPC支持debug API）
  - sequential方法: 顺序扫描slot 0-N（仅能获取简单变量）

  默认: 优先尝试trace，失败则降级到sequential
        """
    )

    parser.add_argument(
        '--filter',
        dest='filters',
        action='append',
        help='日期过滤器（可重复使用）'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='强制重新收集，即使attack_state.json已存在'
    )

    parser.add_argument(
        '--storage-depth',
        type=int,
        default=DEFAULT_STORAGE_DEPTH,
        help=f'存储扫描深度（用于sequential方法，默认: {DEFAULT_STORAGE_DEPTH}）'
    )

    # Trace相关参数
    trace_group = parser.add_mutually_exclusive_group()
    trace_group.add_argument(
        '--use-trace',
        action='store_true',
        default=True,
        help='使用trace方法收集storage（默认启用）'
    )
    trace_group.add_argument(
        '--no-trace',
        action='store_true',
        help='禁用trace方法，仅使用sequential扫描'
    )
    trace_group.add_argument(
        '--trace-only',
        action='store_true',
        help='仅使用trace方法，失败则跳过（不降级到sequential）'
    )

    parser.add_argument(
        '--limit',
        type=int,
        help='限制处理数量（用于测试）'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='启用调试日志'
    )

    args = parser.parse_args()

    # 设置日志级别
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 检查foundry.toml
    if not FOUNDRY_TOML.exists():
        logger.error(f"未找到foundry.toml: {FOUNDRY_TOML}")
        sys.exit(1)

    # 确定trace使用策略
    use_trace = not args.no_trace  # 默认True，除非指定--no-trace
    trace_only = args.trace_only

    if args.no_trace:
        logger.info("模式: Sequential扫描（trace已禁用）")
    elif args.trace_only:
        logger.info("模式: 仅Trace（不降级）")
    else:
        logger.info("模式: Trace优先 + Sequential降级")

    if args.force:
        logger.info("覆盖策略: 启用 --force，所有事件将重新收集")
    else:
        logger.info("覆盖策略: 默认跳过已有 attack_state.json 的事件，使用 --force 可取消跳过")

    # 创建RPC管理器
    logger.info("加载RPC配置...")
    rpc_manager = RPCManager(FOUNDRY_TOML)

    # 创建收集器
    collector = AttackStateCollector(
        rpc_manager=rpc_manager,
        storage_depth=args.storage_depth,
        use_trace=use_trace,
        trace_only=trace_only
    )

    # 执行收集
    try:
        collector.collect_all(
            date_filters=args.filters,
            skip_existing=not args.force,
            limit=args.limit
        )
    except KeyboardInterrupt:
        logger.info("\n\n用户中断")
        collector._print_summary()

if __name__ == '__main__':
    main()
