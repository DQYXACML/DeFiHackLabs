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
from concurrent.futures import ThreadPoolExecutor, as_completed

# 禁用整数字符串转换限制（处理大型区块链数据时需要）
# Python 3.10.4+ 默认限制为4300位十进制数字
# 某些RPC可能返回超长数据，需要禁用此限制
sys.set_int_max_str_digits(0)

try:
    from web3 import Web3
    from web3.exceptions import Web3Exception
except ImportError:
    print("错误：需要安装web3库")
    print("请运行: pip install web3")
    sys.exit(1)

try:
    from eth_utils import keccak
except ImportError:
    print("错误：需要安装eth-utils库")
    print("请运行: pip install eth-utils")
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

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("错误：需要安装requests和urllib3库")
    print("请运行: pip install requests urllib3")
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
LOG_DIR = PROJECT_ROOT / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / 'collect_attack_states.log'
file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logging.getLogger().addHandler(file_handler)

# 收集配置
DEFAULT_STORAGE_DEPTH = 100  # 扫描storage的深度
RPC_TIMEOUT = 30  # RPC超时（秒）
RPC_RETRY_TIMES = 3  # 重试次数
RPC_RETRY_DELAY = 2  # 重试延迟（秒）
REQUEST_DELAY = 0.1  # 请求间隔，避免rate limit

# 并发配置 (阶段3优化: 增加并发度)
MAX_CONCURRENT_ADDRESSES = 10  # 最大并发处理地址数 (优化: 5→10)
MAX_CONCURRENT_SLOTS = 20  # 最大并发读取storage slot数 (优化: 10→20)
BATCH_SIZE = 50  # 批量RPC请求大小(优化:从20增至50)
BATCH_RPC_ENABLED = True  # 启用批量RPC请求(新增)

# Multicall3配置 (阶段2优化)
MULTICALL3_ADDRESS = '0xcA11bde05977b3631167028862bE2a173976CA11'  # 标准Multicall3地址
MULTICALL3_ENABLED = True  # 启用Multicall3优化ERC20余额查询
MULTICALL3_BATCH_SIZE = 100  # 单次Multicall最大调用数

# HTTP连接池配置 (HTTP连接池优化)
HTTP_POOL_SIZE = 50  # 连接池大小
HTTP_MAX_RETRIES = 3  # 自动重试次数
HTTP_BACKOFF_FACTOR = 0.3  # 重试退避因子

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

    # 链上数据补全字段(来自OnChainDataFetcher,可选)
    onchain_name: Optional[str] = None  # 从链上获取的合约名称
    symbol: Optional[str] = None  # ERC20 token symbol
    decimals: Optional[int] = None  # ERC20 decimals
    is_erc20: Optional[bool] = None  # 是否为ERC20代币
    semantic_type: Optional[str] = None  # 语义类型: wrapped_token, uniswap_v2_pair等
    aliases: Optional[list] = None  # 别名列表(包含symbol, interface name等)

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
    erc20_balance_slot: Optional[int] = None

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
# HTTP连接池管理
# ============================================================================

class HTTPSessionPool:
    """HTTP连接池管理器 - 为所有RPC请求提供共享session,减少TCP/TLS握手开销"""

    def __init__(self, pool_size: int = 50, max_retries: int = 3):
        """
        初始化连接池

        Args:
            pool_size: 连接池大小(默认50)
            max_retries: 自动重试次数(默认3)
        """
        self.logger = logging.getLogger(__name__ + '.HTTPSessionPool')
        self.session = self._create_optimized_session(pool_size, max_retries)
        self.logger.info(f"HTTP连接池初始化: pool_size={pool_size}, max_retries={max_retries}")

    def _create_optimized_session(self, pool_size: int, max_retries: int):
        """创建优化的requests Session,配置连接池和重试策略"""
        try:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
        except ImportError as e:
            self.logger.error(f"无法导入必要的库: {e}")
            self.logger.error("请运行: pip install requests urllib3")
            raise

        session = requests.Session()

        # 配置重试策略
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=0.3,  # 重试延迟: 0.3s, 0.6s, 1.2s...
            status_forcelist=[429, 500, 502, 503, 504],  # 对这些状态码重试
            allowed_methods=["POST", "GET"]
        )

        # 配置HTTP适配器(连接池)
        adapter = HTTPAdapter(
            pool_connections=pool_size,      # 连接池大小
            pool_maxsize=pool_size * 2,      # 最大连接数
            max_retries=retry_strategy,      # 重试策略
            pool_block=False                 # 非阻塞模式
        )

        # 挂载适配器到session
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        # 设置默认headers
        session.headers.update({
            'Connection': 'keep-alive',
            'Content-Type': 'application/json',
            'User-Agent': 'DeFiHackLabs-AttackStateCollector/2.0'
        })

        return session

    def post(self, url: str, **kwargs):
        """
        使用连接池发送POST请求

        Args:
            url: 请求URL
            **kwargs: 传递给requests.post的参数

        Returns:
            requests.Response对象
        """
        return self.session.post(url, **kwargs)

    def get(self, url: str, **kwargs):
        """使用连接池发送GET请求"""
        return self.session.get(url, **kwargs)

# ============================================================================
# RPC配置加载
# ============================================================================

class RPCManager:
    """RPC端点管理器"""

    # POA链列表 - 这些链使用Proof of Authority共识，extraData字段超过32字节
    # 需要注入geth_poa_middleware来正确处理区块头
    POA_CHAINS = {'bsc', 'polygon', 'gnosis', 'avalanche', 'fantom', 'moonriver', 'moonbeam'}

    def __init__(self, foundry_toml_path: Path):
        self.logger = logging.getLogger(__name__ + '.RPCManager')
        self.web3_instances: Dict[str, Web3] = {}
        self.rpc_endpoints = self._load_rpc_endpoints(foundry_toml_path)
        self.poa_configured: Set[str] = set()
        self.session_pool = HTTPSessionPool()  # 初始化共享HTTP连接池

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

    def _create_session_provider(self, rpc_url: str):
        """
        创建使用共享session的HTTPProvider

        通过替换HTTPProvider的make_request方法,使其使用共享的session pool
        这样可以复用TCP连接,减少握手开销
        """
        from web3 import HTTPProvider

        provider = HTTPProvider(rpc_url, request_kwargs={'timeout': RPC_TIMEOUT})

        # 保存原始的make_request方法
        original_make_request = provider.make_request
        session = self.session_pool.session

        # 定义使用共享session的make_request
        def make_request_with_session(method, params):
            """使用共享session发送RPC请求"""
            request_data = provider.encode_rpc_request(method, params)

            try:
                response = session.post(
                    rpc_url,
                    data=request_data,
                    headers={'Content-Type': 'application/json'},
                    timeout=RPC_TIMEOUT
                )
                response.raise_for_status()
                # 返回解析后的JSON字典，而不是原始bytes
                # web3.py期望make_request返回解析后的响应
                return response.json()
            except Exception as e:
                # 降级到原始方法(如果session请求失败)
                self.logger.debug(f"Session请求失败,降级到原始方法: {e}")
                return original_make_request(method, params)

        # 替换make_request方法
        provider.make_request = make_request_with_session

        return provider

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
                # 使用共享session的HTTPProvider
                provider = self._create_session_provider(rpc_url)

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

    # 匹配bytes32交易哈希变量，如: bytes32 private constant attackTx = hex"247f4b3d...";
    BYTES32_VAR_PATTERN = re.compile(
        r'bytes32\s+(?:private\s+|public\s+)?(?:constant\s+)?(\w+)\s*=\s*hex["\']([a-fA-F0-9]+)["\']',
        re.MULTILINE
    )

    # 匹配攻击交易哈希注释
    # 支持格式：
    #   // Attack Tx : 0x123...
    #   // Attack Transaction: https://arbiscan.io/tx/0x123...
    #   // Attack Tx : https://etherscan.io/tx/0x123...
    #   // Attack Tx : https://app.blocksec.com/explorer/tx/eth/0x123...
    #   // TX : https://app.blocksec.com/explorer/tx/bsc/0x123...
    #   // Tx: 0x123...
    #   // Attack Tx (WBTC) : https://explorer.phalcon.xyz/tx/eth/0x123...
    #   // One of the attack txs : https://app.blocksec.com/explorer/tx/arbitrum/0x123...
    #   // Attack Tx1 : https://optimistic.etherscan.io/tx/0x123...
    #   // Attack Tx2 : https://optimistic.etherscan.io/tx/0x456...
    # 注意: 优先匹配包含"Attack"关键词的行,避免误匹配代码中的其他tx注释
    ATTACK_TX_PATTERN = re.compile(
        r'(?:One of the\s+)?attack\s+(?:tx|transaction)(?:\d+)?s?\s*(?:\([^)]+\))?\s*:.*?(0x[a-fA-F0-9]{64})|'  # Attack Tx/Tx1/Tx2 (大小写不敏感)
        r'^\s*//\s*(?:TX|Tx)(?:\d+)?\s*:.*?(0x[a-fA-F0-9]{64})',  # 独立的TX:/TX1:/TX2:行
        re.MULTILINE | re.IGNORECASE  # 添加IGNORECASE标志
    )

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.ForkExtractor')

    def _resolve_tx_hash_to_block(self, tx_hash: str, chain: str, rpc_manager: 'RPCManager') -> Optional[int]:
        """
        通过交易哈希查询区块号

        注意: Foundry的createSelectFork(txHash)会fork到该交易**执行前**的状态,
        但仍在同一区块内。因此我们直接返回交易所在区块号。

        Args:
            tx_hash: 交易哈希(不含0x前缀或含0x前缀)
            chain: 链名称
            rpc_manager: RPC管理器

        Returns:
            交易所在的区块号(createSelectFork会fork到交易执行前状态)
        """
        # 标准化交易哈希格式
        if not tx_hash.startswith('0x'):
            tx_hash = '0x' + tx_hash

        self.logger.info(f"  查询交易哈希对应的区块号: {tx_hash[:16]}...")

        try:
            # 获取Web3实例
            w3 = rpc_manager.get_web3(chain)
            if not w3:
                self.logger.error(f"  无法获取链 {chain} 的Web3实例")
                return None

            # 查询交易回执
            tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
            if not tx_receipt:
                self.logger.error(f"  交易不存在或pending: {tx_hash}")
                return None

            # 提取区块号
            block_number = tx_receipt.get('blockNumber')
            if block_number is None:
                self.logger.error(f"  交易回执中缺少blockNumber字段")
                return None

            # 直接返回区块号(createSelectFork会fork到该交易执行前,但在同一区块)
            self.logger.info(f"  交易所在区块: {block_number} (将fork到交易执行前状态)")

            return block_number

        except Exception as e:
            self.logger.error(f"  查询交易哈希失败: {e}")
            return None

    def extract_fork_info(self, exp_file: Path, rpc_manager: Optional['RPCManager'] = None) -> Optional[ForkInfo]:
        """
        提取fork信息

        Args:
            exp_file: exp文件路径
            rpc_manager: RPC管理器(可选,用于解析交易哈希变量)

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

        # 解析区块号表达式(传递chain和rpc_manager用于交易哈希解析)
        block_number = self._parse_block_expression(block_expr, content, chain, rpc_manager)

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

    def _parse_block_expression(self, expr: str, content: str, chain: str = None,
                                rpc_manager: Optional['RPCManager'] = None, depth: int = 0) -> Optional[int]:
        """
        解析区块号表达式

        Args:
            expr: 区块号表达式
            content: 文件内容
            chain: 链名称(用于解析交易哈希)
            rpc_manager: RPC管理器(用于解析交易哈希)
            depth: 递归深度

        Returns:
            解析后的区块号或None
        """

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
            # 先检查是否是bytes32交易哈希变量
            bytes32_match = self.BYTES32_VAR_PATTERN.search(content)
            if bytes32_match and bytes32_match.group(1) == expr:
                # 发现bytes32变量,提取交易哈希
                tx_hash_hex = bytes32_match.group(2)
                self.logger.info(f"  检测到bytes32交易哈希变量: {expr} = 0x{tx_hash_hex[:16]}...")

                # 需要RPC管理器来查询区块号
                if rpc_manager is None or chain is None:
                    self.logger.error(f"  无法解析交易哈希变量 {expr}: 缺少RPC管理器或链名称")
                    return None

                # 调用交易哈希转区块号方法
                block_number = self._resolve_tx_hash_to_block(tx_hash_hex, chain, rpc_manager)
                return block_number

            # 尝试匹配uint256/uint/int变量
            var_pattern = re.compile(
                rf'(?:uint256|uint|int)\s+(?:\w+\s+)*{re.escape(expr)}\s*=\s*([^;]+);'
            )
            var_match = var_pattern.search(content)
            if var_match:
                value_expr = var_match.group(1).strip()
                return self._parse_block_expression(value_expr, content, chain, rpc_manager, depth + 1)

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

        # 提取哈希（可能在group(1)或group(2)中,取非None的那个）
        tx_hash = match.group(1) or match.group(2)
        if not tx_hash:
            self.logger.warning(f"正则匹配成功但未提取到哈希值: {exp_file.name}")
            return None

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
                 use_trace: bool = True, trace_only: bool = False, enable_concurrent: bool = True):
        self.rpc_manager = rpc_manager
        self.storage_depth = storage_depth
        self.use_trace = use_trace
        self.trace_only = trace_only
        self.enable_concurrent = enable_concurrent  # 是否启用并发
        self.logger = logging.getLogger(__name__ + '.StateCollector')
        # Keep track of chains whose RPC endpoints do not support trace APIs to avoid repeated failures
        self.unsupported_trace_chains: Set[str] = set()
        # 缓存trace结果,避免对同一交易重复调用debug_traceTransaction
        # 格式: {tx_hash: prestate_dict}
        self.trace_cache: Dict[str, Dict] = {}

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
            # 清除旧的trace缓存,避免内存泄漏
            if attack_tx_hash not in self.trace_cache:
                self.trace_cache.clear()

        try:
            # 获取区块信息
            block = self._retry_call(lambda: w3.eth.get_block(block_number))
            if not block:
                self.logger.error(f"无法获取区块 {block_number}")
                return None

            # 参与攻击的地址集合，用于后续ERC20余额查询
            holder_candidates: List[str] = []
            holder_candidate_set: Set[str] = set()
            for addr_info in addresses:
                try:
                    checksum_addr = Web3.to_checksum_address(addr_info.address)
                except Exception as exc:
                    self.logger.debug(f"    跳过非法地址 {addr_info.address}: {exc}")
                    continue
                key = checksum_addr.lower()
                if key in holder_candidate_set:
                    continue
                holder_candidate_set.add(key)
                holder_candidates.append(checksum_addr)

            # 收集每个地址的状态
            address_states = {}

            if self.enable_concurrent and len(addresses) > 3:
                # 并发处理多个地址
                self.logger.info(f"  使用并发模式处理 {len(addresses)} 个地址 (workers={MAX_CONCURRENT_ADDRESSES})")
                address_states = self._collect_addresses_concurrent(
                    chain, w3, addresses, block_number, attack_tx_hash, holder_candidates
                )
            else:
                # 串行处理(小数量或禁用并发)
                for i, addr_info in enumerate(addresses, 1):
                    self.logger.debug(f"    [{i}/{len(addresses)}] {addr_info.address}")
                    state = self._collect_address_state(
                        chain,
                        w3,
                        addr_info.address,
                        block_number,
                        attack_tx_hash,
                        holder_candidates
                    )
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
                    try:
                        checksum_addr = Web3.to_checksum_address(discovered_addr)
                        key = checksum_addr.lower()
                        if key not in holder_candidate_set:
                            holder_candidate_set.add(key)
                            holder_candidates.append(checksum_addr)
                    except Exception:
                        checksum_addr = discovered_addr
                    state = self._collect_address_state(
                        chain,
                        w3,
                        checksum_addr,
                        block_number,
                        attack_tx_hash,
                        holder_candidates
                    )
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

    def _collect_addresses_concurrent(self, chain: str, w3: Web3, addresses: List[AddressInfo],
                                     block_number: int, attack_tx_hash: Optional[str],
                                     holder_candidates: List[str]) -> Dict[str, Dict]:
        """
        并发收集多个地址的状态

        Args:
            chain: 链名称
            w3: Web3实例
            addresses: 地址列表
            block_number: 区块号
            attack_tx_hash: 攻击交易哈希
            holder_candidates: ERC20持有者候选列表

        Returns:
            地址状态字典
        """
        address_states = {}

        def collect_single(addr_info: AddressInfo) -> Tuple[str, Optional[Dict], Optional[str]]:
            """收集单个地址的状态(线程安全)"""
            try:
                state = self._collect_address_state(
                    chain, w3, addr_info.address, block_number,
                    attack_tx_hash, holder_candidates
                )
                if state:
                    state_dict = asdict(state)
                    state_dict['name'] = addr_info.name or 'Unknown'
                    return (addr_info.address, state_dict, None)
                return (addr_info.address, None, None)
            except Exception as e:
                return (addr_info.address, None, str(e))

        # 使用线程池并发处理
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_ADDRESSES) as executor:
            # 提交所有任务
            future_to_addr = {
                executor.submit(collect_single, addr_info): addr_info
                for addr_info in addresses
            }

            # 收集结果
            completed = 0
            for future in as_completed(future_to_addr):
                addr_info = future_to_addr[future]
                completed += 1

                try:
                    address, state_dict, error = future.result()
                    if state_dict:
                        address_states[address] = state_dict
                        self.logger.debug(f"    [{completed}/{len(addresses)}] ✓ {address}")
                    elif error:
                        self.logger.warning(f"    [{completed}/{len(addresses)}] ✗ {address}: {error}")
                    else:
                        self.logger.debug(f"    [{completed}/{len(addresses)}] ⊙ {address} (无状态)")

                except Exception as e:
                    self.logger.error(f"    [{completed}/{len(addresses)}] ✗ {addr_info.address}: {e}")

        return address_states

    def _collect_address_state(self, chain: str, w3: Web3, address: str,
                              block_number: int, attack_tx_hash: Optional[str] = None,
                              holder_candidates: Optional[List[str]] = None) -> Optional[StateSnapshot]:
        """收集单个地址的状态"""
        start_time = time.perf_counter()
        base_time = storage_time = erc20_time = 0.0
        try:
            # 标准化地址
            address = Web3.to_checksum_address(address)

            # 基础数据
            stage_start = time.perf_counter()
            balance = self._retry_call(lambda: w3.eth.get_balance(address, block_number))
            nonce = self._retry_call(lambda: w3.eth.get_transaction_count(address, block_number))
            code = self._retry_call(lambda: w3.eth.get_code(address, block_number))
            base_time = time.perf_counter() - stage_start

            if balance is None or nonce is None or code is None:
                return None

            is_contract = len(code) > 0

            # 存储数据（只对合约收集）
            storage = {}
            if is_contract:
                stage_start = time.perf_counter()
                storage = self._collect_storage(chain, w3, address, block_number, attack_tx_hash)
                storage_time = time.perf_counter() - stage_start

            # ERC20余额（只对合约收集）
            erc20_balances = {}
            erc20_balance_slot = None
            if is_contract and holder_candidates:
                stage_start = time.perf_counter()
                erc20_balances, erc20_balance_slot = self._collect_erc20_balances(
                    w3=w3,
                    token_address=address,
                    block_number=block_number,
                    holder_candidates=holder_candidates
                )
                erc20_time = time.perf_counter() - stage_start

            return StateSnapshot(
                balance_wei=str(balance),
                balance_eth=str(w3.from_wei(balance, 'ether')),
                nonce=nonce,
                code=code.hex(),
                code_size=len(code),
                is_contract=is_contract,
                storage=storage,
                erc20_balances=erc20_balances,
                erc20_balance_slot=erc20_balance_slot
            )

        except Exception as e:
            self.logger.warning(f"收集地址 {address} 状态失败: {e}")
            return None
        finally:
            total_time = time.perf_counter() - start_time
            self.logger.debug(
                f"      地址 {address} 耗时: total={total_time:.2f}s base={base_time:.2f}s "
                f"storage={storage_time:.2f}s erc20={erc20_time:.2f}s"
            )

    def _collect_erc20_balances(self, w3: Web3, token_address: str, block_number: int,
                                holder_candidates: List[str]) -> Tuple[Dict[str, str], Optional[int]]:
        """
        通过 balanceOf 调用收集ERC20代币余额，并尝试推断 _balances 映射所在的slot
        优化: 使用Multicall3批量查询所有holder的余额
        """

        balances: Dict[str, str] = {}

        try:
            checksum_token = Web3.to_checksum_address(token_address)
        except Exception:
            return balances, None

        normalized_token = checksum_token.lower()
        unique_holders: List[str] = []
        seen: Set[str] = set()
        for holder in holder_candidates:
            try:
                checksum_holder = Web3.to_checksum_address(holder)
            except Exception:
                continue
            holder_key = checksum_holder.lower()
            if holder_key == normalized_token or holder_key in seen:
                continue
            seen.add(holder_key)
            unique_holders.append(checksum_holder)

        if not unique_holders:
            return balances, None

        raw_balances: Dict[str, int] = {}
        is_erc20 = False

        # ============ Multicall3优化: 批量查询所有holder余额 ============
        if MULTICALL3_ENABLED and len(unique_holders) > 3:
            self.logger.debug(f"      使用Multicall3批量查询 {len(unique_holders)} 个holder的余额")

            try:
                # 获取RPC端点URL
                provider = w3.provider
                rpc_url = None
                if hasattr(provider, 'endpoint_uri'):
                    rpc_url = provider.endpoint_uri
                elif hasattr(provider, '_endpoint_uri'):
                    rpc_url = provider._endpoint_uri

                if rpc_url:
                    # 首先检查Multicall3合约在目标区块是否存在
                    # (Multicall3于2022年3月部署,区块号约14353601)
                    multicall3_code = None
                    try:
                        multicall3_code = w3.eth.get_code(MULTICALL3_ADDRESS, block_number)
                    except Exception as e:
                        self.logger.debug(f"      检查Multicall3合约失败: {e}")

                    if not multicall3_code or len(multicall3_code) == 0:
                        self.logger.debug(f"      Multicall3合约在区块{block_number}不存在,降级到串行模式")
                    else:
                        # 构造Multicall3.aggregate3调用
                        # aggregate3(Call3[] calls) returns (Result[] results)
                        # Call3 = (address target, bool allowFailure, bytes callData)
                        # Result = (bool success, bytes returnData)

                        calls = []
                        for holder in unique_holders:
                            call_data = self._encode_balance_of_call(holder)
                            # 编码单个Call3: (token_address, true, balanceOf_calldata)
                            calls.append({
                                'target': checksum_token,
                                'allowFailure': True,
                                'callData': call_data
                            })

                        # 编码aggregate3调用数据
                        # selector: aggregate3((address,bool,bytes)[])
                        aggregate3_selector = '0x82ad56cb'  # keccak256('aggregate3((address,bool,bytes)[])')[0:4]

                        # 手动编码calls数组 (更可靠)
                        encoded_calls = self._encode_multicall3_aggregate3(calls)
                        multicall_data = aggregate3_selector + encoded_calls

                        # 发送eth_call请求
                        block_hex = hex(block_number)
                        rpc_payload = {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "eth_call",
                            "params": [
                                {
                                    "to": MULTICALL3_ADDRESS,
                                    "data": multicall_data
                                },
                                block_hex
                            ]
                        }

                        # 使用共享session pool发送请求(优化: 复用TCP连接)
                        response = self.rpc_manager.session_pool.post(
                            rpc_url,
                            json=rpc_payload,
                            timeout=RPC_TIMEOUT
                        )

                        if response.status_code == 200:
                            resp_data = response.json()
                            if 'result' in resp_data and resp_data['result']:
                                # 解码返回结果
                                result_data = resp_data['result']
                                decoded_results = self._decode_multicall3_results(result_data, len(unique_holders))

                                success_count = 0
                                for holder, (success, return_data) in zip(unique_holders, decoded_results):
                                    if success and return_data:
                                        try:
                                            # return_data是uint256 (32字节)
                                            if len(return_data) >= 64:  # 至少32字节
                                                value = int(return_data[-64:], 16)  # 取最后32字节
                                                raw_balances[holder] = value
                                                if value > 0:
                                                    balances[holder] = str(value)
                                                success_count += 1
                                                is_erc20 = True
                                        except Exception as e:
                                            self.logger.debug(f"      解码余额失败 {holder}: {e}")

                                if success_count > 0:
                                    self.logger.debug(f"      Multicall3成功获取 {success_count}/{len(unique_holders)} 个余额")

                                    # 检测balance slot
                                    balance_slot = self._detect_erc20_balance_slot(
                                        w3, checksum_token, block_number, raw_balances
                                    )
                                    return balances, balance_slot
                            else:
                                self.logger.debug(f"      Multicall3调用失败,降级到串行模式")
                        else:
                            self.logger.debug(f"      Multicall3 HTTP错误 {response.status_code}")

            except Exception as e:
                self.logger.debug(f"      Multicall3异常,降级到串行模式: {e}")

        # ============ 原有串行逻辑 (作为降级方案) ============
        for holder in unique_holders:
            call_data = self._encode_balance_of_call(holder)

            def _do_call(data=call_data):
                return w3.eth.call(
                    {
                        'to': checksum_token,
                        'data': data
                    },
                    block_identifier=block_number
                )

            try:
                raw = self._retry_call(_do_call)
            except Exception as exc:
                if not is_erc20:
                    # 非ERC20，直接返回空结果
                    self.logger.debug(f"      balanceOf检测失败 {token_address}: {exc}")
                    return {}, None
                self.logger.debug(f"      balanceOf调用失败 {token_address}->{holder}: {exc}")
                continue

            if raw is None:
                continue

            is_erc20 = True
            value = int.from_bytes(raw, byteorder='big', signed=False)
            if value > 0:
                balances[holder] = str(value)
                raw_balances[holder] = value
            else:
                raw_balances[holder] = value

        if not is_erc20:
            return {}, None

        balance_slot = self._detect_erc20_balance_slot(
            w3, checksum_token, block_number, raw_balances
        )

        return balances, balance_slot

    def _encode_multicall3_aggregate3(self, calls: List[Dict]) -> str:
        """
        编码Multicall3.aggregate3的调用参数
        calls: [{'target': address, 'allowFailure': bool, 'callData': hex_string}, ...]
        """
        # ABI编码: 动态数组偏移 + 长度 + 每个元素
        parts = []

        # 偏移量(指向数组数据开始位置): 32字节
        parts.append('0000000000000000000000000000000000000000000000000000000000000020')

        # 数组长度
        parts.append(hex(len(calls))[2:].rjust(64, '0'))

        # 每个元素的偏移量(相对于数组数据开始)
        base_offset = len(calls) * 32  # 所有偏移量占用的空间
        current_offset = base_offset
        offsets = []
        encoded_elements = []

        for call in calls:
            offsets.append(hex(current_offset)[2:].rjust(64, '0'))

            # 编码单个Call3: (address, bool, bytes)
            target = call['target'].lower()[2:].rjust(64, '0')
            allow_failure = '0000000000000000000000000000000000000000000000000000000000000001' if call['allowFailure'] else '0000000000000000000000000000000000000000000000000000000000000000'

            # callData是动态bytes
            call_data = call['callData']
            if call_data.startswith('0x'):
                call_data = call_data[2:]
            call_data_len = len(call_data) // 2

            # bytes偏移: 固定为96 (3个32字节后)
            bytes_offset = '0000000000000000000000000000000000000000000000000000000000000060'
            # bytes长度
            bytes_len = hex(call_data_len)[2:].rjust(64, '0')
            # bytes数据 (填充到32字节边界)
            padded_data = call_data.ljust((len(call_data) + 63) // 64 * 64, '0')

            element = target + allow_failure + bytes_offset + bytes_len + padded_data
            encoded_elements.append(element)

            # 计算这个元素占用的空间: 3*32 + 32 + padded_data_len
            element_size = 32 * 3 + 32 + len(padded_data) // 2
            current_offset += element_size

        # 组合: 偏移量数组 + 元素数据
        parts.extend(offsets)
        parts.extend(encoded_elements)

        return ''.join(parts)

    def _decode_multicall3_results(self, result_hex: str, expected_count: int) -> List[Tuple[bool, str]]:
        """
        解码Multicall3.aggregate3的返回结果
        Returns: [(success, returnData), ...]
        """
        results = []

        try:
            if result_hex.startswith('0x'):
                result_hex = result_hex[2:]

            # 跳过动态数组偏移(32字节)
            offset = 64  # 跳过偏移量

            # 读取数组长度
            array_len = int(result_hex[offset:offset+64], 16)
            offset += 64

            # 读取每个元素的偏移量
            element_offsets = []
            for _ in range(array_len):
                elem_offset = int(result_hex[offset:offset+64], 16)
                element_offsets.append(elem_offset)
                offset += 64

            # 基准位置(数组长度后面)
            base_offset = 64 + 64  # 跳过数组偏移和长度

            # 读取每个Result: (bool success, bytes returnData)
            for i, elem_offset in enumerate(element_offsets):
                try:
                    pos = base_offset + elem_offset * 2  # 转为hex字符位置

                    # success (bool, 32字节)
                    success = int(result_hex[pos:pos+64], 16) != 0
                    pos += 64

                    # returnData偏移 (32字节)
                    data_offset = int(result_hex[pos:pos+64], 16)
                    pos += 64

                    # 跳转到数据位置
                    data_pos = base_offset + elem_offset * 2 + data_offset * 2

                    # 数据长度
                    data_len = int(result_hex[data_pos:data_pos+64], 16)
                    data_pos += 64

                    # 读取数据
                    return_data = result_hex[data_pos:data_pos + data_len * 2]

                    results.append((success, return_data))
                except Exception:
                    results.append((False, ''))

        except Exception as e:
            self.logger.debug(f"      解码Multicall3结果失败: {e}")
            # 返回空结果
            return [(False, '')] * expected_count

        # 补齐缺失的结果
        while len(results) < expected_count:
            results.append((False, ''))

        return results

    @staticmethod
    def _encode_balance_of_call(holder: str) -> str:
        """编码 balanceOf(holder) 调用数据"""
        address_hex = holder.lower()[2:]
        return StateCollector.BALANCE_OF_SELECTOR + address_hex.rjust(64, '0')

    def _detect_erc20_balance_slot(self, w3: Web3, token_address: str, block_number: int,
                                   balances: Dict[str, int]) -> Optional[int]:
        """
        根据采集到的余额反推 _balances 映射的slot（仅需一个非零余额即可）
        """
        if not balances:
            return None

        # 选取第一个非零余额作为样本；若全部为0，则无法推断
        sample_holder = None
        sample_value = None
        for holder, amount in balances.items():
            if amount > 0:
                sample_holder = holder
                sample_value = amount
                break

        if sample_holder is None:
            return None

        holder_bytes = bytes.fromhex(sample_holder[2:].rjust(64, '0'))

        for slot in range(16):  # 尝试前16个slot，满足绝大多数ERC20实现
            slot_bytes = slot.to_bytes(32, byteorder='big')
            storage_key_bytes = keccak(holder_bytes + slot_bytes)
            storage_key_int = int.from_bytes(storage_key_bytes, byteorder='big')

            try:
                raw = self._retry_call(
                    lambda: w3.eth.get_storage_at(token_address, storage_key_int, block_number)
                )
            except Exception:
                continue

            if raw is None:
                continue

            value = int.from_bytes(raw, byteorder='big', signed=False)
            if value == sample_value:
                return slot

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
                error_msg = str(e)
                # 检测RPC限流或服务器错误
                is_rate_limit = any(keyword in error_msg.lower() for keyword in [
                    '500 server error', '429', 'rate limit', 'too many requests',
                    'quota exceeded', 'internal server error'
                ])

                if is_rate_limit:
                    self.logger.warning(f"      ⚠ Trace方法遇到RPC限流/服务器错误: {e}")
                    self.logger.info(f"      等待10秒后重试...")
                    time.sleep(10)  # 等待RPC恢复

                    # 重试一次trace
                    try:
                        storage = self._collect_storage_from_trace(chain, w3, address, attack_tx_hash, block_number)
                        if storage:
                            self.logger.info(f"      ✓ 重试成功: 获取 {len(storage)} 个slots")
                            return storage
                    except Exception as retry_e:
                        self.logger.warning(f"      ⚠ 重试仍失败: {retry_e}")
                else:
                    self.logger.warning(f"      ⚠ Trace方法失败: {e}")

                if self.trace_only:
                    self.logger.error(f"      ✗ trace-only模式下失败，跳过sequential扫描")
                    return {}
        elif attack_tx_hash and self.use_trace and chain_key in self.unsupported_trace_chains:
            self.logger.debug(f"      Trace已对 {chain} 禁用，改用sequential扫描")

        # 方法2: 降级到sequential扫描
        if not self.trace_only:
            self.logger.debug(f"      → 使用sequential扫描")
            # 如果是从trace失败降级,添加额外延迟避免连续请求
            if attack_tx_hash and self.use_trace:
                self.logger.debug(f"      从trace降级,添加5秒延迟避免RPC限流...")
                time.sleep(5)
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

            # 检查缓存
            if tx_hash in self.trace_cache:
                self.logger.debug(f"      → 使用缓存的trace结果")
                prestate = self.trace_cache[tx_hash]
            else:
                # 调用debug_traceTransaction with prestateTracer
                # prestateTracer返回交易执行前所有被访问地址的状态
                self.logger.debug(f"      → 调用debug_traceTransaction (首次)")
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

                # 缓存prestate结果,供后续地址使用
                self.trace_cache[tx_hash] = prestate
                self.logger.debug(f"      ✓ Trace结果已缓存 (包含{len(prestate)}个地址)")

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

                # 解析所有slot
                slot_list = []
                for slot_hex, _ in touched_storage.items():
                    try:
                        if slot_hex.startswith('0x'):
                            slot_int = int(slot_hex, 16)
                        else:
                            slot_int = int(slot_hex, 16)
                        slot_list.append(slot_int)
                    except Exception as e:
                        self.logger.debug(f"      解析slot {slot_hex} 失败: {e}")
                        continue

                # 使用批量读取或串行读取
                if self.enable_concurrent and len(slot_list) > BATCH_SIZE:
                    # 批量读取模式
                    self.logger.debug(f"      使用批量读取模式 ({len(slot_list)} slots)")
                    storage = self._batch_read_storage(w3, address, slot_list, block_number)
                else:
                    # 串行读取模式(兼容旧逻辑)
                    for slot_int in slot_list:
                        try:
                            value = self._retry_call(
                                lambda s=slot_int: w3.eth.get_storage_at(address, s, block_number)
                            )

                            # 保存所有值，包括零值（攻击可能利用未初始化状态）
                            if value is not None:
                                storage[str(slot_int)] = value.hex()

                        except Exception as e:
                            self.logger.debug(f"      读取slot {slot_int} 失败: {e}")
                            continue

            else:
                self.logger.debug(f"      Trace结果中没有storage字段")

            return storage

        except Exception as e:
            # 捕获所有异常并重新抛出，让上层决定是否降级
            raise Exception(f"debug_traceTransaction失败: {e}")

    def _make_batch_rpc_request(self, w3: Web3, rpc_requests: List[Dict]) -> List[Optional[Any]]:
        """
        执行批量JSON-RPC请求 (使用HTTP直接发送)

        Args:
            w3: Web3实例
            rpc_requests: RPC请求列表,每个请求格式:
                      {'method': 'eth_getStorageAt', 'params': [address, slot, block]}

        Returns:
            结果列表,顺序与请求对应,失败的为None
        """
        try:
            # 获取RPC端点URL
            provider = w3.provider
            rpc_url = None

            # 尝试获取endpoint_uri
            if hasattr(provider, 'endpoint_uri'):
                rpc_url = provider.endpoint_uri
            elif hasattr(provider, '_endpoint_uri'):
                rpc_url = provider._endpoint_uri
            elif hasattr(provider, 'provider_uri'):
                rpc_url = provider.provider_uri

            if not rpc_url:
                self.logger.debug("      无法获取RPC URL,降级到串行模式")
                return [None] * len(rpc_requests)

            # 构造JSON-RPC batch请求
            batch_payload = [
                {
                    "jsonrpc": "2.0",
                    "id": i,
                    "method": req['method'],
                    "params": req['params']
                }
                for i, req in enumerate(rpc_requests)
            ]

            # 使用共享session pool发送批量请求(优化: 复用TCP连接)
            response = self.rpc_manager.session_pool.post(
                rpc_url,
                json=batch_payload,
                timeout=RPC_TIMEOUT
            )

            if response.status_code != 200:
                self.logger.warning(f"      批量RPC HTTP错误: {response.status_code}")
                return [None] * len(rpc_requests)

            response_data = response.json()

            # 解析结果(按id排序)
            results = [None] * len(rpc_requests)
            if isinstance(response_data, list):
                for item in response_data:
                    if isinstance(item, dict) and 'id' in item:
                        idx = item['id']
                        if isinstance(idx, int) and 0 <= idx < len(results):
                            if 'result' in item:
                                results[idx] = item['result']
                            elif 'error' in item:
                                self.logger.debug(f"      批量RPC错误 id={idx}: {item['error']}")
            else:
                self.logger.warning(f"      批量RPC返回格式异常: {type(response_data)}")
                return [None] * len(rpc_requests)

            return results

        except requests.exceptions.Timeout:
            self.logger.warning(f"      批量RPC请求超时")
            return [None] * len(rpc_requests)
        except Exception as e:
            self.logger.warning(f"      批量RPC请求失败: {e}")
            return [None] * len(rpc_requests)

    def _batch_read_storage(self, w3: Web3, address: str, slots: List[int],
                           block_number: int) -> Dict[str, str]:
        """
        批量读取storage slots (优先使用批量RPC,失败降级到并发/串行)

        Args:
            w3: Web3实例
            address: 合约地址
            slots: slot列表
            block_number: 区块号

        Returns:
            存储字典 {slot: value}
        """
        storage = {}
        block_hex = hex(block_number)

        # 方式1: 优先使用批量RPC请求(最快)
        if BATCH_RPC_ENABLED and len(slots) > 5:
            self.logger.debug(f"      使用批量RPC读取 {len(slots)} 个slots")

            # 分批发送(避免单次请求过大)
            for i in range(0, len(slots), BATCH_SIZE):
                batch_slots = slots[i:i + BATCH_SIZE]

                # 构造批量请求
                rpc_requests = [
                    {
                        'method': 'eth_getStorageAt',
                        'params': [address, hex(slot), block_hex]
                    }
                    for slot in batch_slots
                ]

                # 发送批量请求
                results = self._make_batch_rpc_request(w3, rpc_requests)

                # 解析结果
                success_count = 0
                for slot, result in zip(batch_slots, results):
                    if result is not None:
                        # result可能是hex字符串或bytes
                        if isinstance(result, str):
                            storage[str(slot)] = result if result.startswith('0x') else '0x' + result
                        elif isinstance(result, bytes):
                            storage[str(slot)] = result.hex()
                        else:
                            # 尝试转换为bytes
                            try:
                                storage[str(slot)] = bytes(result).hex()
                            except:
                                self.logger.debug(f"      无法解析slot {slot}结果: {type(result)}")
                        success_count += 1

                self.logger.debug(f"      批量RPC成功获取 {success_count}/{len(batch_slots)} 个slots")

                # 如果批量RPC失败率过高(>50%),降级到串行模式处理剩余slots
                if success_count < len(batch_slots) * 0.5:
                    self.logger.warning(f"      批量RPC失败率过高,剩余slots将使用串行模式")
                    failed_slots = [s for s, r in zip(batch_slots, results) if r is None]
                    for slot in failed_slots:
                        try:
                            value = self._retry_call(
                                lambda s=slot: w3.eth.get_storage_at(address, s, block_number)
                            )
                            if value is not None:
                                storage[str(slot)] = value.hex()
                        except Exception as e:
                            self.logger.debug(f"      串行读取slot {slot}失败: {e}")

            return storage

        # 方式2: 并发读取(适用于批量RPC不可用或slot数量中等)
        if len(slots) >= MAX_CONCURRENT_SLOTS:
            self.logger.debug(f"      使用并发读取 {len(slots)} 个slots")

            def read_single_slot(slot: int) -> Tuple[int, Optional[bytes]]:
                """读取单个slot"""
                try:
                    value = w3.eth.get_storage_at(address, slot, block_number)
                    return (slot, value)
                except Exception as e:
                    self.logger.debug(f"      读取slot {slot} 失败: {e}")
                    return (slot, None)

            # 使用线程池并发读取
            with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_SLOTS) as executor:
                futures = {executor.submit(read_single_slot, slot): slot for slot in slots}

                for future in as_completed(futures):
                    try:
                        slot, value = future.result()
                        if value is not None:
                            storage[str(slot)] = value.hex()
                    except Exception as e:
                        self.logger.debug(f"      并发读取失败: {e}")

        else:
            # 方式3: 串行读取(适用于slot数量较少)
            self.logger.debug(f"      使用串行读取 {len(slots)} 个slots")
            for slot in slots:
                try:
                    value = self._retry_call(
                        lambda s=slot: w3.eth.get_storage_at(address, s, block_number)
                    )
                    if value is not None:
                        storage[str(slot)] = value.hex()
                except Exception as e:
                    self.logger.debug(f"      读取slot {slot} 失败: {e}")

        return storage

    def _sequential_scan(self, w3: Web3, address: str, block_number: int) -> Dict[str, str]:
        """
        顺序扫描存储槽（传统方法，仅能获取简单变量）
        优化: 使用批量RPC请求 (50个slots/批次)

        Args:
            w3: Web3实例
            address: 合约地址
            block_number: 区块号

        Returns:
            存储字典 {slot: value}
        """
        storage = {}
        slots = list(range(self.storage_depth))

        # 使用批量RPC读取
        if BATCH_RPC_ENABLED and len(slots) > 5:
            self.logger.debug(f"      使用批量RPC扫描 {len(slots)} 个slots")
            storage = self._batch_read_storage(w3, address, slots, block_number)
            return storage

        # 降级到串行读取
        for slot in slots:
            try:
                value = self._retry_call(
                    lambda: w3.eth.get_storage_at(address, slot, block_number)
                )
                if value is not None:
                    storage[str(slot)] = value.hex()

                # 每10个slot添加短暂延迟,避免RPC限流
                if (slot + 1) % 10 == 0:
                    time.sleep(0.2)

            except Exception as e:
                self.logger.debug(f"读取slot {slot} 失败: {e}")
                break

        return storage

    def _discover_addresses_from_storage(self, w3: Web3, address_states: Dict[str, Dict],
                                         block_number: int, attack_tx_hash: Optional[str] = None) -> List[str]:
        """
        从已收集的存储槽中发现新的合约地址（批量优化版本）

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

        # 第一阶段：收集所有潜在地址（不做RPC调用）
        potential_addresses = []  # [(checksum_addr, source_addr, slot), ...]
        seen_potential = set()

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
                    if potential_addr.lower() in seen_potential:
                        continue

                    try:
                        checksum_addr = Web3.to_checksum_address(potential_addr)
                        seen_potential.add(potential_addr.lower())
                        potential_addresses.append((checksum_addr, addr, slot))
                    except Exception:
                        continue

        if not potential_addresses:
            return []

        self.logger.debug(f"      发现 {len(potential_addresses)} 个潜在地址，批量检查中...")

        # 第二阶段：批量检查是否是合约
        block_hex = hex(block_number)
        batch_size = BATCH_SIZE  # 使用全局配置的批量大小

        for i in range(0, len(potential_addresses), batch_size):
            batch = potential_addresses[i:i + batch_size]

            # 构造批量eth_getCode请求
            rpc_requests = [
                {
                    'method': 'eth_getCode',
                    'params': [addr_info[0], block_hex]
                }
                for addr_info in batch
            ]

            # 执行批量请求
            if BATCH_RPC_ENABLED:
                results = self._make_batch_rpc_request(w3, rpc_requests)
            else:
                # 降级到串行模式
                results = []
                for req in rpc_requests:
                    try:
                        code = w3.eth.get_code(req['params'][0], block_number)
                        results.append(code.hex() if code else '0x')
                    except Exception:
                        results.append(None)

            # 处理结果
            for j, result in enumerate(results):
                if result is None:
                    continue

                # 检查code是否非空（0x 或空字符串表示不是合约）
                if result and result != '0x' and len(result) > 2:
                    checksum_addr, source_addr, slot = batch[j]
                    self.logger.debug(f"      发现合约地址: {checksum_addr} (from {source_addr} slot {slot})")
                    discovered.add(checksum_addr)

            # 批次之间短暂延迟避免rate limit
            if i + batch_size < len(potential_addresses):
                time.sleep(REQUEST_DELAY)

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
                 use_trace: bool = True, trace_only: bool = False, collect_after: bool = True,
                 enable_concurrent: bool = True):
        self.rpc_manager = rpc_manager
        self.fork_extractor = ForkExtractor()
        self.state_collector = StateCollector(rpc_manager, storage_depth, use_trace, trace_only, enable_concurrent)
        self.collect_after = collect_after  # 是否收集攻击后状态
        self.stats = CollectionStats()
        self.logger = logging.getLogger(__name__ + '.AttackStateCollector')

        # 错误日志文件
        self.error_log = TEST_DIR / 'collection_errors.log'

    def collect_all(self, date_filters: Optional[List[str]] = None,
                   protocol_filter: Optional[str] = None,
                   skip_existing: bool = False, limit: Optional[int] = None):
        """
        收集所有攻击事件的状态

        Args:
            date_filters: 日期过滤器列表，如 ["2024-01"]
            protocol_filter: 协议名过滤器，如 "XSIJ_exp"
            skip_existing: 跳过已有state文件（默认True，使用--force时为False）
            limit: 限制处理数量（用于测试）
        """
        self.logger.info("=" * 80)
        self.logger.info("开始收集攻击状态")
        self.logger.info("=" * 80)

        # 查找所有事件
        events = self._find_all_events(date_filters, protocol_filter)
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

    def _find_all_events(self, date_filters: Optional[List[str]] = None,
                        protocol_filter: Optional[str] = None) -> List[Tuple[str, str, Path]]:
        """
        查找所有事件目录

        Args:
            date_filters: 日期过滤器列表，如 ["2024-01"]
            protocol_filter: 协议名过滤器，如 "XSIJ_exp"
        """
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

            # 应用日期过滤器
            if date_filters and not any(month_dir.name.startswith(f) for f in date_filters):
                continue

            # 遍历事件目录
            for event_dir in sorted(month_dir.iterdir()):
                if not event_dir.is_dir():
                    continue

                # 应用协议过滤器
                if protocol_filter and event_dir.name != protocol_filter:
                    continue

                events.append((month_dir.name, event_dir.name, event_dir))

        return events

    def _get_attack_block_number(self, chain: str, attack_tx_hash: str) -> Optional[int]:
        """
        通过攻击交易哈希获取攻击所在的区块号

        Args:
            chain: 链名称
            attack_tx_hash: 攻击交易哈希

        Returns:
            攻击交易所在的区块号，或None（如果获取失败）
        """
        w3 = self.rpc_manager.get_web3(chain)
        if not w3:
            return None

        try:
            tx_receipt = self._retry_call(
                lambda: w3.eth.get_transaction_receipt(attack_tx_hash)
            )
            if not tx_receipt:
                self.logger.error(f"  获取攻击交易回执失败: {attack_tx_hash}")
                return None

            block_number = tx_receipt.get('blockNumber')
            if block_number is None:
                self.logger.error(f"  交易回执中缺少blockNumber字段")
                return None

            return block_number

        except Exception as e:
            self.logger.error(f"  获取攻击交易区块号失败: {e}")
            return None

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

    def _process_event(self, month: str, event_name: str, event_dir: Path) -> bool:
        """
        处理单个事件

        Returns:
            是否成功
        """
        event_start = time.perf_counter()
        # 1. 查找对应的exp文件
        exp_file = TEST_DIR / month / f"{event_name}.sol"
        if not exp_file.exists():
            self.logger.warning(f"  未找到exp文件: {exp_file}")
            self.logger.info(f"  事件耗时: {time.perf_counter() - event_start:.2f}s")
            return False

        # 2. 提取fork信息(传递rpc_manager用于解析交易哈希变量)
        fork_info = self.fork_extractor.extract_fork_info(exp_file, self.rpc_manager)
        if not fork_info:
            self.logger.warning("  无法提取fork信息")
            self.logger.info(f"  事件耗时: {time.perf_counter() - event_start:.2f}s")
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
            self.logger.info(f"  事件耗时: {time.perf_counter() - event_start:.2f}s")
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
            self.logger.info(f"  事件耗时: {time.perf_counter() - event_start:.2f}s")
            return False

        if not state.get('addresses'):
            self.logger.error("  收集到的地址列表为空，可能是RPC请求失败或地址配置错误")
            self.logger.info(f"  事件耗时: {time.perf_counter() - event_start:.2f}s")
            return False

        # 6. 保存攻击前状态
        state_file = event_dir / 'attack_state.json'
        try:
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)

            self.logger.debug(f"  攻击前状态保存到: {state_file}")

        except Exception as e:
            self.logger.error(f"  保存攻击前状态失败: {e}")
            return False

        # 7. 收集并保存攻击后状态（如果有攻击交易哈希）
        if attack_tx_hash and self.collect_after:
            self.logger.info("  开始收集攻击后状态...")

            # 添加延迟避免RPC限流
            time.sleep(2.0)

            # 7a. 获取攻击区块号
            attack_block_number = self._get_attack_block_number(fork_info.chain, attack_tx_hash)
            if not attack_block_number:
                self.logger.warning("  无法获取攻击区块号，跳过攻击后状态收集")
            else:
                self.logger.info(f"  攻击区块号: {attack_block_number}")

                # 7b. 收集攻击后状态
                # 关键修复: 攻击后也应该使用trace方法,通过prestateTracer获取被访问的槽位
                # 然后读取这些槽位在攻击区块的最终值,避免sequential扫描导致的超时
                state_after = self.state_collector.collect_state(
                    fork_info.chain,
                    attack_block_number,  # 使用攻击区块号
                    addresses,
                    attack_tx_hash  # 修复: 使用攻击交易哈希进行trace,避免慢速sequential扫描
                )

                if not state_after:
                    self.logger.warning("  攻击后状态收集失败")
                elif not state_after.get('addresses'):
                    self.logger.warning("  收集到的攻击后地址列表为空")
                else:
                    # 7c. 保存攻击后状态
                    state_after_file = event_dir / 'attack_state_after.json'
                    try:
                        with open(state_after_file, 'w', encoding='utf-8') as f:
                            json.dump(state_after, f, indent=2, ensure_ascii=False)

                        self.logger.info(f"  ✓ 攻击后状态保存到: {state_after_file}")

                    except Exception as e:
                        self.logger.error(f"  保存攻击后状态失败: {e}")

        elif not attack_tx_hash:
            self.logger.debug("  无攻击交易哈希，跳过攻击后状态收集")
        elif not self.collect_after:
            self.logger.debug("  --before-only 模式，跳过攻击后状态收集")

        self.logger.info(f"  事件耗时: {time.perf_counter() - event_start:.2f}s")
        return True

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
  # 收集所有事件的攻击前和攻击后状态（默认行为）
  python src/test/collect_attack_states.py

  # 只处理特定月份，收集前后状态
  python src/test/collect_attack_states.py --filter 2024-01

  # 只处理特定协议
  python src/test/collect_attack_states.py --protocol XSIJ_exp --force

  # 结合日期和协议过滤
  python src/test/collect_attack_states.py --filter 2024-01 --protocol XSIJ_exp --force

  # 仅收集攻击前状态，跳过攻击后
  python src/test/collect_attack_states.py --filter 2024-01 --before-only

  # 强制使用sequential扫描（不用trace）
  python src/test/collect_attack_states.py --no-trace

  # 仅使用trace方法，失败则跳过
  python src/test/collect_attack_states.py --trace-only

  # 强制覆盖已有attack_state.json和attack_state_after.json
  python src/test/collect_attack_states.py --force

  # 测试模式（只处理5个）
  python src/test/collect_attack_states.py --limit 5 --debug

  # 禁用并发处理（串行模式，更稳定但较慢）
  python src/test/collect_attack_states.py --no-concurrent

方法说明:
  - trace方法: 使用debug_traceTransaction获取攻击交易访问的所有storage slots
              包括mappings和动态数组（需要RPC支持debug API）
  - sequential方法: 顺序扫描slot 0-N（仅能获取简单变量）

  默认: 优先尝试trace，失败则降级到sequential

收集策略:
  - 默认: 收集攻击前状态(attack_state.json) + 攻击后状态(attack_state_after.json)
  - --before-only: 仅收集攻击前状态（保持原有行为）

性能优化:
  1. Trace缓存: 同一攻击交易的trace结果会被缓存，避免重复调用debug_traceTransaction
  2. 并发处理: 默认启用，同时处理多个地址和存储槽（MAX_CONCURRENT_ADDRESSES=5, MAX_CONCURRENT_SLOTS=10）
  3. 批量RPC: 对大量存储槽使用批量读取，减少网络延迟

  预期性能提升: 对于50+地址的项目，从43分钟降至2-3分钟（约97%加速）
        """
    )

    parser.add_argument(
        '--filter',
        dest='filters',
        action='append',
        help='日期过滤器（可重复使用），如: --filter 2024-01'
    )

    parser.add_argument(
        '--protocol',
        dest='protocol_filter',
        type=str,
        help='协议名过滤器，只处理匹配的协议，如: --protocol XSIJ_exp'
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

    # 攻击后状态收集参数
    after_group = parser.add_mutually_exclusive_group()
    after_group.add_argument(
        '--collect-after',
        action='store_true',
        default=True,
        help='收集攻击后状态（默认启用）'
    )
    after_group.add_argument(
        '--before-only',
        action='store_true',
        help='仅收集攻击前状态，跳过攻击后状态收集'
    )

    parser.add_argument(
        '--limit',
        type=int,
        help='限制处理数量（用于测试）'
    )

    parser.add_argument(
        '--no-concurrent',
        action='store_true',
        help='禁用并发处理(串行模式,更稳定但较慢)'
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
    enable_concurrent = not args.no_concurrent  # 默认True，除非指定--no-concurrent

    if args.no_trace:
        logger.info("模式: Sequential扫描（trace已禁用）")
    elif args.trace_only:
        logger.info("模式: 仅Trace（不降级）")
    else:
        logger.info("模式: Trace优先 + Sequential降级")

    # 确定攻击后状态收集策略
    collect_after = not args.before_only  # 默认True，除非指定--before-only

    if args.before_only:
        logger.info("收集策略: 仅收集攻击前状态")
    else:
        logger.info("收集策略: 收集攻击前和攻击后状态")

    if args.force:
        logger.info("覆盖策略: 启用 --force，所有事件将重新收集")
    else:
        logger.info("覆盖策略: 默认跳过已有 attack_state.json 的事件，使用 --force 可取消跳过")

    # 并发模式提示
    if enable_concurrent:
        logger.info(f"并发模式: 启用 (地址并发数={MAX_CONCURRENT_ADDRESSES}, 存储槽并发数={MAX_CONCURRENT_SLOTS})")
    else:
        logger.info("并发模式: 禁用 (串行处理模式)")

    # 创建RPC管理器
    logger.info("加载RPC配置...")
    rpc_manager = RPCManager(FOUNDRY_TOML)

    # 创建收集器
    collector = AttackStateCollector(
        rpc_manager=rpc_manager,
        storage_depth=args.storage_depth,
        use_trace=use_trace,
        trace_only=trace_only,
        collect_after=collect_after,  # 传入攻击后状态收集参数
        enable_concurrent=enable_concurrent  # 传入并发处理参数
    )

    # 执行收集
    try:
        collector.collect_all(
            date_filters=args.filters,
            protocol_filter=args.protocol_filter,  # 传入协议过滤器
            skip_existing=not args.force,
            limit=args.limit
        )
    except KeyboardInterrupt:
        logger.info("\n\n用户中断")
        collector._print_summary()

if __name__ == '__main__':
    main()
