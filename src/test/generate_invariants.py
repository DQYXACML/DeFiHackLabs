#!/usr/bin/env python3
"""
DeFi攻击不变量自动生成工具

功能：
1. 分析攻击脚本(.sol文件)，识别攻击模式
2. 分析攻击前状态(attack_state.json)，提取关键数据
3. 自动生成能够检测此类攻击的不变量规则
4. 输出invariants.json文件到项目目录

支持的不变量类型：
- flash_loan_depth: 闪电贷嵌套深度限制
- loop_iterations: 循环迭代次数限制
- balance_change_rate: 余额变化率限制
- reentrancy_depth: 重入深度限制
- call_sequence: 调用序列模式检测
- token_balance_ratio: 代币余额比例限制

作者: Claude Code
版本: 1.0.0
"""

import re
import json
import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from datetime import datetime
from collections import defaultdict

# ============================================================================
# 配置
# ============================================================================

LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# 路径配置
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
EXTRACTED_DIR = PROJECT_ROOT / 'extracted_contracts'
TEST_DIR = PROJECT_ROOT / 'src' / 'test'

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class Invariant:
    """不变量定义"""
    id: str
    type: str
    severity: str  # critical, high, medium, low
    description: str
    threshold: Any
    reason: str
    target_contract: Optional[str] = None
    target_function: Optional[str] = None
    monitored_address: Optional[str] = None
    monitored_token: Optional[str] = None
    pattern: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class AttackPattern:
    """攻击模式"""
    pattern_type: str  # loop, flashloan, reentrancy, price_manipulation
    confidence: float  # 0.0 - 1.0
    evidence: List[str]
    extracted_values: Dict[str, Any]

@dataclass
class ContractState:
    """合约状态"""
    address: str
    name: str
    balance_wei: str
    storage: Dict[str, str]
    is_contract: bool

# ============================================================================
# 攻击模式分析器
# ============================================================================

class AttackPatternAnalyzer:
    """分析Solidity代码，识别攻击模式"""

    # 模式匹配正则表达式
    LOOP_PATTERN = re.compile(
        r'(?:while|for)\s*\([^)]*?(\w+)\s*<\s*(\d+)',
        re.MULTILINE
    )

    FLASHLOAN_PATTERN = re.compile(
        r'\.(?:flash|flashLoan)\s*\(',
        re.MULTILINE | re.IGNORECASE
    )

    CALLBACK_PATTERN = re.compile(
        r'function\s+(?:callback|onFlashLoan|receiveFlashLoan)\s*\(',
        re.MULTILINE
    )

    REENTRANCY_PATTERN = re.compile(
        r'\.call\{|\.delegatecall\{|\.staticcall\{',
        re.MULTILINE
    )

    TOKEN_OPERATION_PATTERN = re.compile(
        r'\.(?:transfer|approve|swap|bond|debond|mint|burn)\s*\(',
        re.MULTILINE
    )

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.AttackPatternAnalyzer')

    def analyze(self, sol_file: Path) -> List[AttackPattern]:
        """分析攻击脚本，返回识别的攻击模式"""
        try:
            with open(sol_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.logger.error(f"读取文件失败 {sol_file}: {e}")
            return []

        patterns = []

        # 检测循环模式
        loop_pattern = self._detect_loop_pattern(content)
        if loop_pattern:
            patterns.append(loop_pattern)

        # 检测闪电贷模式
        flashloan_pattern = self._detect_flashloan_pattern(content)
        if flashloan_pattern:
            patterns.append(flashloan_pattern)

        # 检测重入模式
        reentrancy_pattern = self._detect_reentrancy_pattern(content)
        if reentrancy_pattern:
            patterns.append(reentrancy_pattern)

        # 检测代币操作模式
        token_pattern = self._detect_token_operations(content)
        if token_pattern:
            patterns.append(token_pattern)

        return patterns

    def _detect_loop_pattern(self, content: str) -> Optional[AttackPattern]:
        """检测循环攻击模式"""
        matches = self.LOOP_PATTERN.findall(content)
        if not matches:
            return None

        # 找到最大的循环次数
        max_iterations = 0
        loop_var = ""
        for var, count in matches:
            iterations = int(count)
            if iterations > max_iterations:
                max_iterations = iterations
                loop_var = var

        if max_iterations <= 1:
            return None

        # 提取循环体内的关键调用
        evidence = []

        # 查找循环体
        loop_match = re.search(
            rf'while\s*\([^)]*{loop_var}[^)]*\)\s*\{{([^}}]+)\}}',
            content,
            re.MULTILINE | re.DOTALL
        )

        if loop_match:
            loop_body = loop_match.group(1)

            # 检查循环体内是否有闪电贷调用
            if 'flash' in loop_body.lower():
                evidence.append(f"循环体内调用flash函数{max_iterations}次")

            # 检查循环体内的其他关键操作
            if 'bond' in loop_body or 'mint' in loop_body:
                evidence.append(f"循环体内重复执行bond/mint操作")

            if 'transfer' in loop_body or 'swap' in loop_body:
                evidence.append(f"循环体内重复执行token操作")

        return AttackPattern(
            pattern_type='loop',
            confidence=0.9,
            evidence=evidence or [f"检测到{max_iterations}次循环"],
            extracted_values={
                'iterations': max_iterations,
                'loop_variable': loop_var
            }
        )

    def _detect_flashloan_pattern(self, content: str) -> Optional[AttackPattern]:
        """检测闪电贷模式"""
        flashloan_calls = self.FLASHLOAN_PATTERN.findall(content)
        callback_funcs = self.CALLBACK_PATTERN.findall(content)

        if not flashloan_calls:
            return None

        evidence = []
        evidence.append(f"检测到{len(flashloan_calls)}个闪电贷调用")

        if callback_funcs:
            evidence.append(f"存在{len(callback_funcs)}个callback函数")

        # 检测闪电贷调用是否在循环中
        in_loop = False
        for i, line in enumerate(content.split('\n')):
            if 'flash' in line.lower() and '(' in line:
                # 向上查找是否在循环中
                context = '\n'.join(content.split('\n')[max(0, i-10):i])
                if 'while' in context or 'for' in context:
                    in_loop = True
                    evidence.append("闪电贷调用在循环内（可能的重入攻击）")
                    break

        confidence = 0.9 if (callback_funcs and in_loop) else 0.7

        return AttackPattern(
            pattern_type='flashloan',
            confidence=confidence,
            evidence=evidence,
            extracted_values={
                'flashloan_count': len(flashloan_calls),
                'has_callback': len(callback_funcs) > 0,
                'in_loop': in_loop
            }
        )

    def _detect_reentrancy_pattern(self, content: str) -> Optional[AttackPattern]:
        """检测重入模式"""
        # 查找callback函数
        callbacks = self.CALLBACK_PATTERN.findall(content)
        if not callbacks:
            return None

        evidence = []

        # 在callback函数中查找状态修改操作
        for match in re.finditer(self.CALLBACK_PATTERN, content):
            start = match.start()
            # 提取callback函数体（简化版）
            brace_count = 0
            callback_body = ""
            for i, char in enumerate(content[start:]):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        callback_body = content[start:start+i+1]
                        break

            # 检查callback中是否有状态修改
            if 'bond' in callback_body or 'mint' in callback_body:
                evidence.append("callback函数中调用bond/mint（可能的重入利用）")

            if 'transfer' in callback_body:
                evidence.append("callback函数中执行token转账")

        if not evidence:
            return None

        return AttackPattern(
            pattern_type='reentrancy',
            confidence=0.8,
            evidence=evidence,
            extracted_values={
                'callback_count': len(callbacks)
            }
        )

    def _detect_token_operations(self, content: str) -> Optional[AttackPattern]:
        """检测代币操作模式"""
        operations = self.TOKEN_OPERATION_PATTERN.findall(content)

        if len(operations) < 3:  # 少于3个操作不认为是模式
            return None

        # 统计操作类型
        op_counts = defaultdict(int)
        for op in operations:
            op_name = op.replace('.', '').replace('(', '')
            op_counts[op_name] += 1

        evidence = []
        for op, count in op_counts.items():
            if count > 1:
                evidence.append(f"{op}操作执行{count}次")

        return AttackPattern(
            pattern_type='token_operations',
            confidence=0.6,
            evidence=evidence,
            extracted_values={
                'total_operations': len(operations),
                'operation_types': dict(op_counts)
            }
        )

# ============================================================================
# 状态分析器
# ============================================================================

class StateAnalyzer:
    """分析attack_state.json，提取关键状态信息"""

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.StateAnalyzer')

    def analyze(self, state_file: Path) -> Dict[str, ContractState]:
        """分析状态文件，返回合约状态字典"""
        try:
            with open(state_file, 'r') as f:
                state_data = json.load(f)
        except Exception as e:
            self.logger.error(f"读取状态文件失败 {state_file}: {e}")
            return {}

        contracts = {}

        addresses_data = state_data.get('addresses', {})
        for address, data in addresses_data.items():
            contracts[address] = ContractState(
                address=address,
                name=data.get('name', 'Unknown'),
                balance_wei=data.get('balance_wei', '0'),
                storage=data.get('storage', {}),
                is_contract=data.get('is_contract', False)
            )

        return contracts

# ============================================================================
# 不变量生成器
# ============================================================================

class InvariantGenerator:
    """基于攻击模式和状态生成不变量"""

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.InvariantGenerator')
        self.invariant_id_counter = 1

    def generate(self,
                 patterns: List[AttackPattern],
                 states: Dict[str, ContractState],
                 project_name: str,
                 attack_tx: Optional[str] = None) -> List[Invariant]:
        """生成不变量列表"""

        invariants = []

        for pattern in patterns:
            if pattern.pattern_type == 'loop':
                inv = self._generate_loop_invariant(pattern, states)
                if inv:
                    invariants.append(inv)

            elif pattern.pattern_type == 'flashloan':
                inv = self._generate_flashloan_invariant(pattern, states)
                if inv:
                    invariants.append(inv)

            elif pattern.pattern_type == 'reentrancy':
                inv = self._generate_reentrancy_invariant(pattern, states)
                if inv:
                    invariants.append(inv)

            elif pattern.pattern_type == 'token_operations':
                inv = self._generate_balance_invariant(pattern, states)
                if inv:
                    invariants.append(inv)

        return invariants

    def _generate_loop_invariant(self, pattern: AttackPattern,
                                 states: Dict[str, ContractState]) -> Optional[Invariant]:
        """生成循环迭代次数不变量"""
        iterations = pattern.extracted_values.get('iterations', 0)

        if iterations <= 2:
            return None

        # 设置阈值为实际迭代次数的一半（或最小为3）
        threshold = max(3, iterations // 2)

        return Invariant(
            id=f"INV_{self._next_id():03d}",
            type='loop_iterations',
            severity='high' if iterations > 10 else 'medium',
            description=f"单个交易中同一函数调用次数不应超过{threshold}次",
            threshold=threshold,
            reason=f"检测到循环{iterations}次执行关键函数调用",
            pattern='; '.join(pattern.evidence),
            metadata={
                'detected_iterations': iterations,
                'pattern_confidence': pattern.confidence
            }
        )

    def _generate_flashloan_invariant(self, pattern: AttackPattern,
                                      states: Dict[str, ContractState]) -> Optional[Invariant]:
        """生成闪电贷深度不变量"""
        in_loop = pattern.extracted_values.get('in_loop', False)

        # 如果在循环中，这是严重的重入风险
        severity = 'critical' if in_loop else 'high'
        threshold = 1 if in_loop else 2

        return Invariant(
            id=f"INV_{self._next_id():03d}",
            type='flash_loan_depth',
            severity=severity,
            description=f"闪电贷嵌套深度不应超过{threshold}",
            threshold=threshold,
            reason='; '.join(pattern.evidence),
            metadata={
                'flashloan_count': pattern.extracted_values.get('flashloan_count', 0),
                'has_callback': pattern.extracted_values.get('has_callback', False),
                'in_loop': in_loop,
                'pattern_confidence': pattern.confidence
            }
        )

    def _generate_reentrancy_invariant(self, pattern: AttackPattern,
                                       states: Dict[str, ContractState]) -> Optional[Invariant]:
        """生成重入深度不变量"""

        return Invariant(
            id=f"INV_{self._next_id():03d}",
            type='reentrancy_depth',
            severity='critical',
            description="重入调用深度不应超过1",
            threshold=1,
            reason='; '.join(pattern.evidence),
            metadata={
                'callback_count': pattern.extracted_values.get('callback_count', 0),
                'pattern_confidence': pattern.confidence
            }
        )

    def _generate_balance_invariant(self, pattern: AttackPattern,
                                    states: Dict[str, ContractState]) -> Optional[Invariant]:
        """生成余额变化率不变量"""

        # 从状态中找到合约地址（有storage的就是合约）
        contract_addresses = [
            addr for addr, state in states.items()
            if state.is_contract and len(state.storage) > 0
        ]

        if not contract_addresses:
            return None

        # 使用第一个合约地址作为监控目标
        target_contract = contract_addresses[0]

        return Invariant(
            id=f"INV_{self._next_id():03d}",
            type='balance_change_rate',
            severity='high',
            description="单次交易中合约余额变化率不应超过50%",
            threshold=0.5,
            reason=f"检测到{pattern.extracted_values.get('total_operations', 0)}个代币操作",
            monitored_address=target_contract,
            metadata={
                'operation_types': pattern.extracted_values.get('operation_types', {}),
                'pattern_confidence': pattern.confidence
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

class InvariantGeneratorController:
    """不变量生成主控制器"""

    def __init__(self):
        self.pattern_analyzer = AttackPatternAnalyzer()
        self.state_analyzer = StateAnalyzer()
        self.invariant_generator = InvariantGenerator()
        self.logger = logging.getLogger(__name__ + '.Controller')

    def generate_for_project(self, project_dir: Path, exp_file: Path) -> Optional[Path]:
        """为单个项目生成不变量"""

        project_name = project_dir.name
        self.logger.info(f"处理项目: {project_name}")

        # 1. 检查必需文件
        state_file = project_dir / 'attack_state.json'
        if not state_file.exists():
            self.logger.warning(f"  缺少attack_state.json")
            return None

        if not exp_file.exists():
            self.logger.warning(f"  缺少exp文件: {exp_file}")
            return None

        # 2. 分析攻击模式
        self.logger.info(f"  分析攻击模式...")
        patterns = self.pattern_analyzer.analyze(exp_file)
        self.logger.info(f"  识别到{len(patterns)}个攻击模式")

        for pattern in patterns:
            self.logger.info(f"    - {pattern.pattern_type} (confidence: {pattern.confidence:.2f})")

        if not patterns:
            self.logger.warning(f"  未识别到攻击模式")
            return None

        # 3. 分析状态
        self.logger.info(f"  分析攻击前状态...")
        states = self.state_analyzer.analyze(state_file)
        self.logger.info(f"  加载了{len(states)}个合约状态")

        # 4. 读取攻击交易哈希（如果有）
        attack_tx = None
        try:
            with open(state_file, 'r') as f:
                state_data = json.load(f)
                attack_tx = state_data.get('metadata', {}).get('attack_tx_hash')
        except:
            pass

        # 5. 生成不变量
        self.logger.info(f"  生成不变量...")
        invariants = self.invariant_generator.generate(
            patterns, states, project_name, attack_tx
        )
        self.logger.info(f"  生成了{len(invariants)}个不变量")

        # 6. 保存结果
        output_file = project_dir / 'invariants.json'
        output_data = {
            'project': project_name,
            'generated_at': datetime.now().isoformat(),
            'attack_tx': attack_tx,
            'patterns_detected': [
                {
                    'type': p.pattern_type,
                    'confidence': p.confidence,
                    'evidence': p.evidence
                }
                for p in patterns
            ],
            'invariants': [asdict(inv) for inv in invariants]
        }

        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            self.logger.info(f"  ✓ 保存到: {output_file}")
            return output_file

        except Exception as e:
            self.logger.error(f"  保存失败: {e}")
            return None

    def generate_batch(self, date_filter: Optional[str] = None):
        """批量生成不变量"""

        self.logger.info("=" * 80)
        self.logger.info("批量生成不变量")
        self.logger.info("=" * 80)

        if not EXTRACTED_DIR.exists():
            self.logger.error(f"提取目录不存在: {EXTRACTED_DIR}")
            return

        success_count = 0
        total_count = 0

        # 遍历月份目录
        for month_dir in sorted(EXTRACTED_DIR.iterdir()):
            if not month_dir.is_dir():
                continue

            if not re.match(r'\d{4}-\d{2}', month_dir.name):
                continue

            if date_filter and not month_dir.name.startswith(date_filter):
                continue

            # 遍历项目目录
            for project_dir in sorted(month_dir.iterdir()):
                if not project_dir.is_dir():
                    continue

                total_count += 1

                # 查找对应的exp文件
                exp_file = TEST_DIR / month_dir.name / f"{project_dir.name}.sol"

                result = self.generate_for_project(project_dir, exp_file)
                if result:
                    success_count += 1

        # 打印摘要
        self.logger.info("\n" + "=" * 80)
        self.logger.info("执行摘要")
        self.logger.info("=" * 80)
        self.logger.info(f"总项目数: {total_count}")
        self.logger.info(f"成功:     {success_count}")
        self.logger.info(f"失败:     {total_count - success_count}")
        self.logger.info("=" * 80)

# ============================================================================
# 命令行接口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='DeFi攻击不变量自动生成工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 为单个项目生成不变量
  python src/test/generate_invariants.py \\
    --project extracted_contracts/2024-01/BarleyFinance_exp \\
    --exp-file src/test/2024-01/BarleyFinance_exp.sol

  # 批量生成（所有2024-01项目）
  python src/test/generate_invariants.py --filter 2024-01

  # 查看生成的不变量
  cat extracted_contracts/2024-01/BarleyFinance_exp/invariants.json | jq
        """
    )

    parser.add_argument(
        '--project',
        type=Path,
        help='单个项目目录路径'
    )

    parser.add_argument(
        '--exp-file',
        type=Path,
        help='对应的exp文件路径'
    )

    parser.add_argument(
        '--filter',
        help='批量处理的日期过滤器（如2024-01）'
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

    controller = InvariantGeneratorController()

    # 单个项目模式
    if args.project and args.exp_file:
        result = controller.generate_for_project(args.project, args.exp_file)
        if result:
            logger.info(f"\n✓ 不变量已生成: {result}")
            sys.exit(0)
        else:
            logger.error("\n✗ 生成失败")
            sys.exit(1)

    # 批量模式
    elif args.filter:
        controller.generate_batch(args.filter)

    else:
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()
