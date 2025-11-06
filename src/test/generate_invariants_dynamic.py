#!/usr/bin/env python3
"""
动态不变量生成工具 - 基于攻击交易实际执行

功能：
1. 自动部署攻击前状态到 Anvil
2. 执行攻击交易并捕获 trace
3. 分析运行时数据（余额、循环、深度等）
4. 基于真实测量值生成不变量
5. 输出到 invariants.json

与静态分析的区别：
- 静态分析: 只看代码，阈值硬编码
- 动态分析: 执行交易，基于真实数据

使用示例：
    python src/test/generate_invariants_dynamic.py \
      --event extracted_contracts/2024-01/BarleyFinance_exp

作者: Claude Code
版本: 1.0.0 (动态分析版本)
"""

import re
import json
import os
import sys
import time
import subprocess
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
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

# ============================================================================
# 配置
# ============================================================================

LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
EXTRACTED_DIR = PROJECT_ROOT / 'extracted_contracts'
TEST_DIR = PROJECT_ROOT / 'src' / 'test'
GENERATED_DEPLOY_DIR = PROJECT_ROOT / 'generated_deploy'

ANVIL_RPC = "http://localhost:8545"
ANVIL_CHAIN_ID = 31337

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class Invariant:
    """不变量定义"""
    id: str
    type: str
    severity: str
    description: str
    threshold: Any
    reason: str
    measured_value: Any  # 新增：实际测量值
    target_contract: Optional[str] = None
    target_function: Optional[str] = None
    monitored_address: Optional[str] = None
    monitored_token: Optional[str] = None
    pattern: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class RuntimeData:
    """运行时捕获的数据"""
    tx_hash: str

    # 余额变化
    balance_changes: Dict[str, Tuple[int, int]]  # address -> (before, after)

    # Trace数据
    call_depth: int
    loop_iterations: Dict[str, int]  # function_sig -> iterations
    flashloan_depth: int
    reentrancy_depth: int

    # 调用统计
    function_calls: Dict[str, int]  # function_sig -> count

    # Gas使用
    gas_used: int

# ============================================================================
# Anvil进程管理
# ============================================================================

class AnvilManager:
    """管理Anvil进程"""

    def __init__(self):
        self.process = None
        self.logger = logging.getLogger(__name__ + '.AnvilManager')

    def start(self, fork_url: Optional[str] = None, fork_block: Optional[int] = None):
        """启动Anvil"""
        cmd = [
            'anvil',
            '--block-base-fee-per-gas', '0',
            '--gas-price', '0'
        ]

        if fork_url and fork_block:
            cmd.extend(['--fork-url', fork_url, '--fork-block-number', str(fork_block)])

        self.logger.info(f"启动Anvil: {' '.join(cmd)}")

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # 等待Anvil启动
        time.sleep(3)

        # 测试连接
        w3 = Web3(Web3.HTTPProvider(ANVIL_RPC))
        if not w3.is_connected():
            raise RuntimeError("无法连接到Anvil")

        self.logger.info(f"✓ Anvil已启动: {ANVIL_RPC}")

    def stop(self):
        """停止Anvil"""
        if self.process:
            self.logger.info("停止Anvil...")
            self.process.terminate()
            self.process.wait(timeout=5)
            self.process = None

# ============================================================================
# 状态部署器
# ============================================================================

class StateDeployer:
    """部署攻击前状态到Anvil"""

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.StateDeployer')

    def deploy(self, event_dir: Path) -> bool:
        """
        部署状态到Anvil

        查找并执行 generated_deploy/script/YYYY-MM/deploy_EventName.py
        """
        event_name = event_dir.name
        month = event_dir.parent.name

        deploy_script = GENERATED_DEPLOY_DIR / 'script' / month / f'deploy_{event_name}.py'

        if not deploy_script.exists():
            self.logger.error(f"未找到部署脚本: {deploy_script}")
            return False

        self.logger.info(f"执行部署脚本: {deploy_script.name}")

        try:
            result = subprocess.run(
                ['python', str(deploy_script)],
                cwd=GENERATED_DEPLOY_DIR,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                self.logger.error(f"部署失败:\n{result.stderr}")
                return False

            self.logger.info("✓ 状态部署成功")
            return True

        except subprocess.TimeoutExpired:
            self.logger.error("部署超时")
            return False
        except Exception as e:
            self.logger.error(f"部署异常: {e}")
            return False

# ============================================================================
# 攻击执行器
# ============================================================================

class AttackExecutor:
    """执行攻击交易并捕获hash"""

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.AttackExecutor')

    def execute(self, exp_file: Path) -> Optional[str]:
        """
        执行攻击并返回交易hash

        方法：
        1. 记录执行前的区块号和交易数
        2. 使用 forge test 执行（会向 Anvil 发送交易）
        3. 查询新增的交易
        """
        self.logger.info(f"执行攻击: {exp_file.name}")

        try:
            w3 = Web3(Web3.HTTPProvider(ANVIL_RPC))

            # 1. 记录执行前的状态
            block_before = w3.eth.block_number
            self.logger.debug(f"  执行前区块号: {block_before}")

            # 2. 执行攻击
            result = subprocess.run(
                [
                    'forge', 'test',
                    '--match-path', str(exp_file),
                    '--fork-url', ANVIL_RPC,
                    '-vvv'
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=120
            )

            # 检查是否执行成功
            if result.returncode != 0:
                self.logger.error(f"Forge test 执行失败:\n{result.stderr}")
                return None

            # 检查测试是否通过（攻击成功）
            if "test result: ok" not in result.stdout.lower():
                self.logger.warning("测试未通过，但继续尝试获取交易")

            # 3. 查询新增的交易
            time.sleep(1)  # 等待区块确认
            block_after = w3.eth.block_number
            self.logger.debug(f"  执行后区块号: {block_after}")

            # 4. 收集执行期间的所有交易
            tx_hashes = []
            for block_num in range(block_before + 1, block_after + 1):
                try:
                    block = w3.eth.get_block(block_num, full_transactions=True)
                    for tx in block['transactions']:
                        tx_hashes.append(tx['hash'].hex())
                except Exception as e:
                    self.logger.debug(f"  获取区块 {block_num} 失败: {e}")

            if not tx_hashes:
                self.logger.error("未找到任何新交易")
                return None

            # 5. 如果有多个交易，选择gas最高的（通常是攻击交易）
            if len(tx_hashes) > 1:
                self.logger.info(f"  找到 {len(tx_hashes)} 个交易，选择gas最高的")

                max_gas_tx = None
                max_gas = 0

                for tx_hash in tx_hashes:
                    try:
                        receipt = w3.eth.get_transaction_receipt(tx_hash)
                        if receipt['gasUsed'] > max_gas:
                            max_gas = receipt['gasUsed']
                            max_gas_tx = tx_hash
                    except:
                        continue

                tx_hash = max_gas_tx or tx_hashes[-1]
            else:
                tx_hash = tx_hashes[0]

            self.logger.info(f"✓ 攻击已执行: {tx_hash[:16]}...")
            return tx_hash

        except subprocess.TimeoutExpired:
            self.logger.error("执行超时")
            return None
        except Exception as e:
            self.logger.error(f"执行异常: {e}")
            import traceback
            self.logger.debug(traceback.format_exc())
            return None

# ============================================================================
# Trace分析器
# ============================================================================

class TraceAnalyzer:
    """分析交易trace，提取运行时数据"""

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.logger = logging.getLogger(__name__ + '.TraceAnalyzer')

    def analyze(self, tx_hash: str, addresses: List[str]) -> Optional[RuntimeData]:
        """
        分析交易trace

        Args:
            tx_hash: 交易hash
            addresses: 关注的地址列表

        Returns:
            RuntimeData或None
        """
        self.logger.info("分析交易trace...")

        try:
            # 1. 获取交易receipt
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)
            gas_used = receipt['gasUsed']

            # 2. 获取交易前后余额
            balance_changes = self._get_balance_changes(tx_hash, addresses)

            # 3. 获取trace数据
            trace = self._get_trace(tx_hash)

            if not trace:
                self.logger.error("无法获取trace数据")
                return None

            # 4. 分析trace
            call_depth = self._analyze_call_depth(trace)
            loop_iterations = self._analyze_loops(trace)
            flashloan_depth = self._analyze_flashloan_depth(trace)
            reentrancy_depth = self._analyze_reentrancy(trace)
            function_calls = self._analyze_function_calls(trace)

            return RuntimeData(
                tx_hash=tx_hash,
                balance_changes=balance_changes,
                call_depth=call_depth,
                loop_iterations=loop_iterations,
                flashloan_depth=flashloan_depth,
                reentrancy_depth=reentrancy_depth,
                function_calls=function_calls,
                gas_used=gas_used
            )

        except Exception as e:
            self.logger.error(f"Trace分析失败: {e}")
            return None

    def _get_balance_changes(self, tx_hash: str, addresses: List[str]) -> Dict[str, Tuple[int, int]]:
        """获取地址余额变化"""
        changes = {}

        tx = self.w3.eth.get_transaction(tx_hash)
        block_number = tx['blockNumber']

        for addr in addresses:
            try:
                # 交易前余额（前一个区块）
                balance_before = self.w3.eth.get_balance(addr, block_number - 1)
                # 交易后余额（当前区块）
                balance_after = self.w3.eth.get_balance(addr, block_number)

                if balance_before != balance_after:
                    changes[addr] = (balance_before, balance_after)
            except Exception as e:
                self.logger.debug(f"获取余额失败 {addr}: {e}")

        return changes

    def _get_trace(self, tx_hash: str) -> Optional[Dict]:
        """获取交易trace"""
        try:
            result = self.w3.provider.make_request(
                'debug_traceTransaction',
                [tx_hash, {'tracer': 'callTracer'}]
            )

            if 'result' in result:
                return result['result']
        except Exception as e:
            self.logger.warning(f"获取trace失败: {e}")

        return None

    def _analyze_call_depth(self, trace: Dict) -> int:
        """分析最大调用深度"""
        def get_depth(node, current_depth=1):
            if 'calls' not in node or not node['calls']:
                return current_depth

            max_depth = current_depth
            for call in node['calls']:
                depth = get_depth(call, current_depth + 1)
                max_depth = max(max_depth, depth)

            return max_depth

        return get_depth(trace)

    def _analyze_loops(self, trace: Dict) -> Dict[str, int]:
        """
        分析循环迭代次数

        通过统计相同函数调用的连续重复次数
        """
        loops = defaultdict(int)

        def traverse(node, path=[]):
            input_data = node.get('input', '')[:10]  # 取函数选择器

            # 检查是否与路径中前一个相同（简化的循环检测）
            if path and path[-1] == input_data:
                loops[input_data] += 1

            new_path = path + [input_data]

            if 'calls' in node:
                for call in node['calls']:
                    traverse(call, new_path)

        traverse(trace)

        return dict(loops)

    def _analyze_flashloan_depth(self, trace: Dict) -> int:
        """
        分析闪电贷嵌套深度

        检测包含 'flash' 关键字的调用链深度
        """
        max_flashloan_depth = 0

        def traverse(node, flashloan_depth=0):
            nonlocal max_flashloan_depth

            # 检查是否是flashloan调用（简化检测）
            input_data = node.get('input', '').lower()
            is_flashloan = 'flash' in str(node.get('to', '')).lower() or len(input_data) > 10

            if is_flashloan:
                flashloan_depth += 1
                max_flashloan_depth = max(max_flashloan_depth, flashloan_depth)

            if 'calls' in node:
                for call in node['calls']:
                    traverse(call, flashloan_depth)

        traverse(trace)

        return max_flashloan_depth

    def _analyze_reentrancy(self, trace: Dict) -> int:
        """
        分析重入深度

        检测同一地址的重复访问深度
        """
        max_reentrancy = 0

        def traverse(node, visited_addresses=[]):
            nonlocal max_reentrancy

            to_addr = node.get('to', '').lower()

            # 计算该地址在路径中出现的次数
            reentrancy_count = visited_addresses.count(to_addr)
            max_reentrancy = max(max_reentrancy, reentrancy_count)

            new_visited = visited_addresses + [to_addr]

            if 'calls' in node:
                for call in node['calls']:
                    traverse(call, new_visited)

        traverse(trace)

        return max_reentrancy

    def _analyze_function_calls(self, trace: Dict) -> Dict[str, int]:
        """统计函数调用次数"""
        calls = defaultdict(int)

        def traverse(node):
            input_data = node.get('input', '')[:10]  # 函数选择器
            if input_data:
                calls[input_data] += 1

            if 'calls' in node:
                for call in node['calls']:
                    traverse(call)

        traverse(trace)

        return dict(calls)

# ============================================================================
# 不变量生成器（基于运行时数据）
# ============================================================================

class DynamicInvariantGenerator:
    """基于运行时数据生成不变量"""

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.DynamicInvariantGenerator')
        self.invariant_id_counter = 1

    def generate(self, runtime_data: RuntimeData, event_name: str) -> List[Invariant]:
        """
        基于运行时数据生成不变量

        使用实际测量值设定阈值（而非硬编码）
        """
        invariants = []

        # 1. 余额变化率不变量
        balance_inv = self._generate_balance_invariant(runtime_data)
        if balance_inv:
            invariants.append(balance_inv)

        # 2. 调用深度不变量
        depth_inv = self._generate_depth_invariant(runtime_data)
        if depth_inv:
            invariants.append(depth_inv)

        # 3. 循环迭代不变量
        loop_inv = self._generate_loop_invariant(runtime_data)
        if loop_inv:
            invariants.append(loop_inv)

        # 4. 闪电贷深度不变量
        flashloan_inv = self._generate_flashloan_invariant(runtime_data)
        if flashloan_inv:
            invariants.append(flashloan_inv)

        # 5. 重入深度不变量
        reentrancy_inv = self._generate_reentrancy_invariant(runtime_data)
        if reentrancy_inv:
            invariants.append(reentrancy_inv)

        # 6. 函数调用次数不变量
        function_inv = self._generate_function_call_invariant(runtime_data)
        if function_inv:
            invariants.append(function_inv)

        return invariants

    def _generate_balance_invariant(self, data: RuntimeData) -> Optional[Invariant]:
        """基于实际余额变化生成不变量"""
        if not data.balance_changes:
            return None

        # 计算最大变化率
        max_change_rate = 0.0
        monitored_address = None

        for addr, (before, after) in data.balance_changes.items():
            if before == 0:
                continue

            change_rate = abs(after - before) / before
            if change_rate > max_change_rate:
                max_change_rate = change_rate
                monitored_address = addr

        if max_change_rate < 0.1:  # 变化率<10%不生成不变量
            return None

        # 阈值 = 实际变化率的 50%（保守）
        threshold = max(0.2, max_change_rate * 0.5)

        severity = 'critical' if max_change_rate > 0.8 else 'high' if max_change_rate > 0.5 else 'medium'

        return Invariant(
            id=f"INV_{self._next_id():03d}",
            type='balance_change_rate',
            severity=severity,
            description=f"单次交易中合约余额变化率不应超过{threshold*100:.0f}%",
            threshold=threshold,
            measured_value=max_change_rate,
            reason=f"观察到最大余额变化率为{max_change_rate*100:.1f}%",
            monitored_address=monitored_address,
            metadata={
                'measured_change_rate': max_change_rate,
                'all_changes': {addr: f"{(abs(after-before)/before)*100:.1f}%"
                               for addr, (before, after) in data.balance_changes.items() if before > 0}
            }
        )

    def _generate_depth_invariant(self, data: RuntimeData) -> Optional[Invariant]:
        """基于实际调用深度生成不变量"""
        if data.call_depth <= 3:  # 深度≤3认为正常
            return None

        # 阈值 = 实际深度的 70%
        threshold = max(3, int(data.call_depth * 0.7))

        severity = 'high' if data.call_depth > 10 else 'medium'

        return Invariant(
            id=f"INV_{self._next_id():03d}",
            type='call_depth',
            severity=severity,
            description=f"单次交易中调用深度不应超过{threshold}层",
            threshold=threshold,
            measured_value=data.call_depth,
            reason=f"观察到调用深度为{data.call_depth}层",
            metadata={
                'measured_depth': data.call_depth
            }
        )

    def _generate_loop_invariant(self, data: RuntimeData) -> Optional[Invariant]:
        """基于实际循环次数生成不变量"""
        if not data.loop_iterations:
            return None

        # 找到最大循环次数
        max_iterations = max(data.loop_iterations.values())

        if max_iterations <= 3:
            return None

        # 阈值 = 实际迭代次数的 50%
        threshold = max(3, int(max_iterations * 0.5))

        severity = 'high' if max_iterations > 10 else 'medium'

        return Invariant(
            id=f"INV_{self._next_id():03d}",
            type='loop_iterations',
            severity=severity,
            description=f"单个交易中循环迭代次数不应超过{threshold}次",
            threshold=threshold,
            measured_value=max_iterations,
            reason=f"观察到最大循环迭代{max_iterations}次",
            metadata={
                'measured_iterations': max_iterations,
                'all_loops': data.loop_iterations
            }
        )

    def _generate_flashloan_invariant(self, data: RuntimeData) -> Optional[Invariant]:
        """基于实际闪电贷深度生成不变量"""
        if data.flashloan_depth == 0:
            return None

        # 阈值 = 实际深度（不允许超过）
        threshold = max(1, data.flashloan_depth)

        severity = 'critical' if data.flashloan_depth > 1 else 'high'

        return Invariant(
            id=f"INV_{self._next_id():03d}",
            type='flash_loan_depth',
            severity=severity,
            description=f"闪电贷嵌套深度不应超过{threshold}",
            threshold=threshold,
            measured_value=data.flashloan_depth,
            reason=f"观察到闪电贷嵌套深度为{data.flashloan_depth}",
            metadata={
                'measured_depth': data.flashloan_depth
            }
        )

    def _generate_reentrancy_invariant(self, data: RuntimeData) -> Optional[Invariant]:
        """基于实际重入深度生成不变量"""
        if data.reentrancy_depth <= 1:
            return None

        # 阈值 = 1（不允许重入）
        threshold = 1

        return Invariant(
            id=f"INV_{self._next_id():03d}",
            type='reentrancy_depth',
            severity='critical',
            description=f"重入调用深度不应超过{threshold}",
            threshold=threshold,
            measured_value=data.reentrancy_depth,
            reason=f"观察到重入深度为{data.reentrancy_depth}",
            metadata={
                'measured_depth': data.reentrancy_depth
            }
        )

    def _generate_function_call_invariant(self, data: RuntimeData) -> Optional[Invariant]:
        """基于函数调用统计生成不变量"""
        if not data.function_calls:
            return None

        # 找到调用次数最多的函数
        max_calls = max(data.function_calls.values())

        if max_calls <= 5:
            return None

        # 阈值 = 实际调用次数的 60%
        threshold = max(5, int(max_calls * 0.6))

        severity = 'high' if max_calls > 20 else 'medium'

        return Invariant(
            id=f"INV_{self._next_id():03d}",
            type='function_call_count',
            severity=severity,
            description=f"单个函数在单次交易中调用次数不应超过{threshold}次",
            threshold=threshold,
            measured_value=max_calls,
            reason=f"观察到单个函数最多调用{max_calls}次",
            metadata={
                'measured_max_calls': max_calls,
                'top_functions': dict(sorted(data.function_calls.items(),
                                           key=lambda x: x[1], reverse=True)[:5])
            }
        )

    def _next_id(self) -> int:
        """获取下一个不变量ID"""
        id_val = self.invariant_id_counter
        self.invariant_id_counter += 1
        return id_val

# ============================================================================
# 主控制器
# ============================================================================

class DynamicInvariantController:
    """动态不变量生成主控制器"""

    def __init__(self):
        self.anvil_manager = AnvilManager()
        self.state_deployer = StateDeployer()
        self.attack_executor = AttackExecutor()
        self.invariant_generator = DynamicInvariantGenerator()
        self.logger = logging.getLogger(__name__ + '.Controller')

    def generate_for_event(self, event_dir: Path) -> bool:
        """
        为单个事件生成动态不变量

        完整流程：
        1. 启动Anvil
        2. 部署状态
        3. 执行攻击
        4. 分析trace
        5. 生成不变量
        6. 保存结果
        """
        event_name = event_dir.name
        month = event_dir.parent.name

        self.logger.info("=" * 80)
        self.logger.info(f"动态生成不变量: {month}/{event_name}")
        self.logger.info("=" * 80)

        try:
            # 1. 启动Anvil
            self.logger.info("\n[1/6] 启动Anvil...")
            self.anvil_manager.start()

            # 2. 部署状态
            self.logger.info("\n[2/6] 部署攻击前状态...")
            if not self.state_deployer.deploy(event_dir):
                return False

            # 3. 执行攻击
            self.logger.info("\n[3/6] 执行攻击交易...")
            exp_file = TEST_DIR / month / f"{event_name}.sol"
            tx_hash = self.attack_executor.execute(exp_file)

            if not tx_hash:
                return False

            # 4. 加载地址列表
            self.logger.info("\n[4/6] 加载地址列表...")
            addresses_file = event_dir / 'addresses.json'
            if not addresses_file.exists():
                self.logger.error("未找到addresses.json")
                return False

            with open(addresses_file, 'r') as f:
                addresses_data = json.load(f)

            addresses = [addr['address'] for addr in addresses_data]
            self.logger.info(f"  加载了 {len(addresses)} 个地址")

            # 5. 分析trace
            self.logger.info("\n[5/6] 分析交易trace...")
            w3 = Web3(Web3.HTTPProvider(ANVIL_RPC))
            trace_analyzer = TraceAnalyzer(w3)

            runtime_data = trace_analyzer.analyze(tx_hash, addresses)

            if not runtime_data:
                return False

            # 打印运行时数据摘要
            self._print_runtime_summary(runtime_data)

            # 6. 生成不变量
            self.logger.info("\n[6/6] 生成不变量...")
            invariants = self.invariant_generator.generate(runtime_data, event_name)

            self.logger.info(f"  生成了 {len(invariants)} 个不变量")

            # 7. 保存结果
            output_file = event_dir / 'invariants.json'
            output_data = {
                'project': event_name,
                'generated_at': datetime.now().isoformat(),
                'generation_method': 'dynamic_analysis',
                'attack_tx': tx_hash,
                'runtime_data_summary': {
                    'call_depth': runtime_data.call_depth,
                    'max_loop_iterations': max(runtime_data.loop_iterations.values()) if runtime_data.loop_iterations else 0,
                    'flashloan_depth': runtime_data.flashloan_depth,
                    'reentrancy_depth': runtime_data.reentrancy_depth,
                    'gas_used': runtime_data.gas_used,
                    'addresses_affected': len(runtime_data.balance_changes)
                },
                'invariants': [asdict(inv) for inv in invariants]
            }

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            self.logger.info(f"\n✓ 成功保存到: {output_file}")
            return True

        except Exception as e:
            self.logger.error(f"生成失败: {e}", exc_info=True)
            return False

        finally:
            # 清理：停止Anvil
            self.anvil_manager.stop()

    def _print_runtime_summary(self, data: RuntimeData):
        """打印运行时数据摘要"""
        self.logger.info("\n  运行时数据摘要:")
        self.logger.info(f"    • 调用深度: {data.call_depth}")
        self.logger.info(f"    • 闪电贷深度: {data.flashloan_depth}")
        self.logger.info(f"    • 重入深度: {data.reentrancy_depth}")
        self.logger.info(f"    • Gas使用: {data.gas_used:,}")

        if data.loop_iterations:
            max_loop = max(data.loop_iterations.values())
            self.logger.info(f"    • 最大循环迭代: {max_loop}次")

        if data.balance_changes:
            self.logger.info(f"    • 余额变化地址数: {len(data.balance_changes)}")
            for addr, (before, after) in list(data.balance_changes.items())[:3]:
                if before > 0:
                    change_pct = ((after - before) / before) * 100
                    self.logger.info(f"      - {addr[:10]}...: {change_pct:+.1f}%")

# ============================================================================
# 命令行接口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='动态不变量生成工具 - 基于攻击交易实际执行',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 为单个事件生成动态不变量
  python src/test/generate_invariants_dynamic.py \\
    --event extracted_contracts/2024-01/BarleyFinance_exp

  # 调试模式
  python src/test/generate_invariants_dynamic.py \\
    --event extracted_contracts/2024-01/BarleyFinance_exp \\
    --debug

方法对比:
  - 静态分析 (generate_invariants.py): 只分析代码，阈值硬编码
  - 动态分析 (本脚本): 执行攻击，基于真实测量值生成阈值

注意:
  - 需要先生成部署脚本 (generated_deploy/)
  - 需要Anvil可执行文件
  - 会自动启动和停止Anvil进程
        """
    )

    parser.add_argument(
        '--event',
        type=Path,
        required=True,
        help='事件目录路径 (如: extracted_contracts/2024-01/BarleyFinance_exp)'
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

    # 检查事件目录
    if not args.event.exists():
        logger.error(f"事件目录不存在: {args.event}")
        sys.exit(1)

    # 检查必要文件
    if not (args.event / 'addresses.json').exists():
        logger.error(f"缺少addresses.json: {args.event / 'addresses.json'}")
        sys.exit(1)

    if not (args.event / 'attack_state.json').exists():
        logger.error(f"缺少attack_state.json: {args.event / 'attack_state.json'}")
        sys.exit(1)

    # 生成不变量
    controller = DynamicInvariantController()

    try:
        success = controller.generate_for_event(args.event)

        if success:
            logger.info("\n" + "=" * 80)
            logger.info("✓ 动态不变量生成成功")
            logger.info("=" * 80)
            sys.exit(0)
        else:
            logger.error("\n" + "=" * 80)
            logger.error("✗ 动态不变量生成失败")
            logger.error("=" * 80)
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\n\n用户中断")
        controller.anvil_manager.stop()
        sys.exit(130)

if __name__ == '__main__':
    main()
