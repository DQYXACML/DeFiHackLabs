#!/usr/bin/env python3
"""
从 Monitor 输出生成存储级不变量

功能：
1. 读取 Go monitor 的分析结果（JSON）
2. 加载 attack_state.json
3. 分析存储槽语义和协议类型
4. 生成存储级不变量（storage-level invariants）
5. 输出到 invariants.json

使用示例：
    # 步骤1：运行 Go monitor
    cd autopath
    ./monitor -rpc http://localhost:8545 -tx 0x<TX> -output analysis.json -v

    # 步骤2：生成存储级不变量
    python src/test/generate_invariants_from_monitor.py \
      --monitor-output autopath/analysis.json \
      --output extracted_contracts/2024-01/BarleyFinance_exp/invariants.json

作者: Claude Code
版本: 2.0.0 (仅存储级不变量)
"""

import json
import argparse
import logging
from pathlib import Path
from typing import Dict, Optional, Any, List
from datetime import datetime

# Import storage invariant analyzer
from storage_invariant_generator import (
    StorageInvariantAnalyzer,
    ContractState as StorageContractState
)

# ============================================================================
# 配置
# ============================================================================

LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# ============================================================================
# Monitor 输出解析器
# ============================================================================

class MonitorOutputParser:
    """解析 Go monitor 的输出"""

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.MonitorOutputParser')

    def parse(self, monitor_file: Path) -> Dict[str, Any]:
        """
        解析 monitor 输出文件

        预期格式：
        {
          "tx_hash": "0x...",
          "violations": [...],
          "runtime_data": {
            "call_depth": 8,
            "loop_iterations": {...},
            "balance_changes": {...},
            ...
          }
        }
        """
        try:
            with open(monitor_file, 'r') as f:
                data = json.load(f)

            self.logger.info(f"成功解析 monitor 输出")
            return data

        except Exception as e:
            self.logger.error(f"解析 monitor 输出失败: {e}")
            return {}

# ============================================================================
# 主控制器
# ============================================================================

class InvariantFromMonitorController:
    """从 Monitor 输出生成存储级不变量的主控制器"""

    def __init__(self):
        self.parser = MonitorOutputParser()
        self.storage_analyzer = StorageInvariantAnalyzer()
        self.logger = logging.getLogger(__name__ + '.Controller')

    def generate(self, monitor_file: Path, output_file: Path, project_name: Optional[str] = None) -> bool:
        """
        生成存储级不变量 + 运行时不变量

        Args:
            monitor_file: Monitor 输出文件
            output_file: 输出的 invariants.json 文件
            project_name: 项目名称（可选）

        Returns:
            是否成功
        """
        self.logger.info("=" * 80)
        self.logger.info("从 Monitor 输出生成存储级 + 运行时不变量")
        self.logger.info("=" * 80)

        # 1. 解析 monitor 输出
        self.logger.info(f"\n[1/4] 解析 monitor 输出: {monitor_file.name}")
        monitor_data = self.parser.parse(monitor_file)

        if not monitor_data:
            self.logger.error("解析失败")
            return False

        # 提取项目名称
        if not project_name:
            project_name = monitor_data.get('project', 'Unknown')

        # 2. 加载 attack_state.json 并生成存储级不变量
        self.logger.info(f"\n[2/4] 生成存储级不变量...")
        storage_analysis = self._analyze_storage_invariants(output_file, project_name)

        if not storage_analysis:
            self.logger.warning("存储级不变量生成失败，继续生成运行时不变量")
            storage_invariants = []
        else:
            storage_invariants = storage_analysis.get('invariants', [])

        # 3. 从 Monitor 运行时数据生成不变量
        self.logger.info(f"\n[3/4] 从 Monitor 运行时数据生成不变量...")
        runtime_invariants = self._generate_runtime_invariants(monitor_data)

        # 4. 保存结果
        self.logger.info(f"\n[4/4] 保存到: {output_file}")

        output_data = {
            'project': project_name,
            'generated_at': datetime.now().isoformat(),
            'generation_method': 'storage_and_runtime_analysis',
            'source_file': str(monitor_file),
            'attack_tx': monitor_data.get('transaction_data', {}).get('tx_hash'),
            'monitor_summary': {
                'gas_used': monitor_data.get('transaction_data', {}).get('gas_used', 0),
                'call_depth': monitor_data.get('transaction_data', {}).get('call_depth', 0),
                'reentrancy_depth': monitor_data.get('transaction_data', {}).get('reentrancy_depth', 0),
                'loop_iterations': monitor_data.get('transaction_data', {}).get('loop_iterations', 0),
            },
            'storage_invariants': storage_invariants,
            'runtime_invariants': runtime_invariants,
            'storage_analysis_metadata': {
                'protocol_info': storage_analysis.get('protocol_info', {}) if storage_analysis else {},
                'relationships_detected': len(storage_analysis.get('relationships', [])) if storage_analysis else 0
            }
        }

        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)

            total_storage = len(storage_invariants)
            total_runtime = len(runtime_invariants)
            total_invariants = total_storage + total_runtime

            self.logger.info("\n" + "=" * 80)
            self.logger.info(f"✓ 成功生成 {total_invariants} 个不变量:")
            self.logger.info(f"  - 存储级不变量: {total_storage}")
            self.logger.info(f"  - 运行时不变量: {total_runtime}")
            self.logger.info("=" * 80)
            return True

        except Exception as e:
            self.logger.error(f"保存失败: {e}")
            return False

    def _analyze_storage_invariants(self, output_file: Path, project_name: str) -> Optional[Dict[str, Any]]:
        """
        分析存储级不变量

        尝试加载 attack_state.json 并运行存储分析

        Args:
            output_file: 输出文件路径（用于推断 attack_state.json 位置）
            project_name: 项目名称

        Returns:
            存储分析结果，如果没有 attack_state.json 则返回 None
        """
        # 推断 attack_state.json 位置
        # 通常在同一目录下: extracted_contracts/2024-01/ProjectName/attack_state.json
        project_dir = output_file.parent
        attack_state_file = project_dir / 'attack_state.json'

        if not attack_state_file.exists():
            self.logger.warning(f"未找到 attack_state.json: {attack_state_file}")
            self.logger.warning("跳过存储级不变量分析")
            return None

        try:
            self.logger.info(f"加载 attack_state.json...")
            with open(attack_state_file, 'r') as f:
                attack_state = json.load(f)

            # 转换为 StorageContractState 格式
            contracts = {}
            for addr, contract_data in attack_state.get('addresses', {}).items():
                contracts[addr] = StorageContractState(
                    address=addr,
                    balance_wei=contract_data.get('balance_wei', '0'),
                    nonce=contract_data.get('nonce', 0),
                    code=contract_data.get('code', ''),
                    code_size=contract_data.get('code_size', 0),
                    is_contract=contract_data.get('is_contract', False),
                    storage=contract_data.get('storage', {}),
                    name=contract_data.get('name', 'Unknown')
                )

            # 运行存储分析
            self.logger.info(f"运行存储槽分析...")
            storage_analysis = self.storage_analyzer.analyze(contracts)

            return storage_analysis

        except Exception as e:
            self.logger.error(f"存储分析失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _generate_runtime_invariants(self, monitor_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从 Monitor 运行时数据生成不变量

        基于实际观察到的运行时行为生成不变量：
        - 循环次数限制
        - 调用深度限制
        - 重入深度限制
        - 余额变化率限制

        Args:
            monitor_data: Monitor 输出的完整数据

        Returns:
            运行时不变量列表
        """
        invariants = []
        tx_data = monitor_data.get('transaction_data', {})

        # 提取运行时指标
        loop_iterations = tx_data.get('loop_iterations', 0)
        call_depth = tx_data.get('call_depth', 0)
        reentrancy_depth = tx_data.get('reentrancy_depth', 0)
        balance_changes = tx_data.get('balance_changes', {})

        self.logger.info(f"  提取到的运行时指标:")
        self.logger.info(f"    - 循环次数: {loop_iterations}")
        self.logger.info(f"    - 调用深度: {call_depth}")
        self.logger.info(f"    - 重入深度: {reentrancy_depth}")
        self.logger.info(f"    - 余额变化: {len(balance_changes)} 个地址")

        # 1. 循环次数限制
        # 基于观察值设置阈值：正常情况不应超过观察值的 50%
        if loop_iterations > 0:
            loop_threshold = max(1, int(loop_iterations * 0.5))
            invariants.append({
                'id': 'RINV_001',
                'type': 'runtime_loop_limit',
                'severity': 'high',
                'description': f'正常交易的循环次数不应超过 {loop_threshold} 次',
                'formula': f'loop_iterations <= {loop_threshold}',
                'threshold': loop_threshold,
                'observed_value': loop_iterations,
                'rationale': f'攻击交易观察到 {loop_iterations} 次循环，正常值应低于 {loop_threshold}'
            })
            self.logger.info(f"  ✓ 生成循环限制不变量: <= {loop_threshold}")

        # 2. 调用深度限制
        # 基于观察值设置阈值：正常情况不应超过观察值的 50%
        if call_depth > 1:
            call_depth_threshold = max(2, int(call_depth * 0.5))
            invariants.append({
                'id': 'RINV_002',
                'type': 'runtime_call_depth_limit',
                'severity': 'medium',
                'description': f'正常交易的调用深度不应超过 {call_depth_threshold}',
                'formula': f'call_depth <= {call_depth_threshold}',
                'threshold': call_depth_threshold,
                'observed_value': call_depth,
                'rationale': f'攻击交易观察到调用深度 {call_depth}，正常值应低于 {call_depth_threshold}'
            })
            self.logger.info(f"  ✓ 生成调用深度限制不变量: <= {call_depth_threshold}")

        # 3. 重入深度限制
        # 正常情况下应该为 0（无重入）
        if reentrancy_depth > 0:
            invariants.append({
                'id': 'RINV_003',
                'type': 'runtime_reentrancy_limit',
                'severity': 'critical',
                'description': '正常交易不应出现重入调用',
                'formula': 'reentrancy_depth == 0',
                'threshold': 0,
                'observed_value': reentrancy_depth,
                'rationale': f'攻击交易检测到重入深度 {reentrancy_depth}，这是异常行为'
            })
            self.logger.info(f"  ⚠️  检测到重入 (depth={reentrancy_depth})，生成重入限制不变量")

        # 4. 余额变化率限制
        # 对于每个发生显著余额变化的地址，生成不变量
        significant_changes = []
        for addr, change_data in balance_changes.items():
            change_rate = abs(change_data.get('change_rate', 0))

            # 只关注变化率 > 0.01% 的地址
            if change_rate > 0.0001:
                significant_changes.append((addr, change_rate, change_data))

        if significant_changes:
            # 找到最大变化率
            max_change_addr, max_change_rate, max_change_data = max(significant_changes, key=lambda x: x[1])

            # 设置阈值为观察值的 50%
            balance_threshold = max(0.0001, max_change_rate * 0.5)

            invariants.append({
                'id': 'RINV_004',
                'type': 'runtime_balance_change_limit',
                'severity': 'high',
                'description': f'单笔交易中关键合约的余额变化率不应超过 {balance_threshold:.2%}',
                'formula': f'max(balance_change_rate) <= {balance_threshold}',
                'threshold': balance_threshold,
                'observed_value': max_change_rate,
                'monitored_addresses': [addr for addr, _, _ in significant_changes],
                'rationale': f'攻击交易中地址 {max_change_addr[:10]}... 的余额变化率为 {max_change_rate:.4%}，正常值应低于 {balance_threshold:.4%}',
                'details': {
                    'max_change_address': max_change_addr,
                    'max_change_before': max_change_data.get('before', 0),
                    'max_change_after': max_change_data.get('after', 0),
                    'max_change_diff': max_change_data.get('difference', 0)
                }
            })
            self.logger.info(f"  ✓ 生成余额变化限制不变量: <= {balance_threshold:.4%}")
            self.logger.info(f"    最大变化: {max_change_addr[:10]}... ({max_change_rate:.4%})")

        self.logger.info(f"  共生成 {len(invariants)} 个运行时不变量")
        return invariants

# ============================================================================
# 命令行接口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='从 Go Monitor 输出生成存储级不变量',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 步骤1：使用 Go monitor 分析攻击
  cd autopath
  ./monitor -rpc http://localhost:8545 -tx 0x<TX> -output analysis.json -v

  # 步骤2：从 monitor 输出生成存储级不变量
  python src/test/generate_invariants_from_monitor.py \\
    --monitor-output autopath/analysis.json \\
    --output extracted_contracts/2024-01/BarleyFinance_exp/invariants.json

  # 或者指定项目名称
  python src/test/generate_invariants_from_monitor.py \\
    --monitor-output autopath/analysis.json \\
    --output extracted_contracts/2024-01/BarleyFinance_exp/invariants.json \\
    --project BarleyFinance_exp

特点:
  • 生成存储级不变量（基于协议业务逻辑）
  • 生成运行时不变量（基于 Monitor 观察到的行为）
  • 自动检测协议类型（Vault/AMM/Lending）
  • 分析存储槽语义和关系
  • 基于实际攻击行为设置合理阈值

运行时不变量类型:
  • 循环次数限制 (loop_iterations)
  • 调用深度限制 (call_depth)
  • 重入深度限制 (reentrancy_depth)
  • 余额变化率限制 (balance_change_rate)
        """
    )

    parser.add_argument(
        '--monitor-output',
        type=Path,
        required=True,
        help='Go monitor 的输出文件（JSON格式）'
    )

    parser.add_argument(
        '--output',
        type=Path,
        required=True,
        help='输出的 invariants.json 文件路径'
    )

    parser.add_argument(
        '--project',
        help='项目名称（可选，默认从 monitor 输出中提取）'
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

    # 检查输入文件
    if not args.monitor_output.exists():
        logger.error(f"Monitor 输出文件不存在: {args.monitor_output}")
        return 1

    # 生成不变量
    controller = InvariantFromMonitorController()

    success = controller.generate(
        monitor_file=args.monitor_output,
        output_file=args.output,
        project_name=args.project
    )

    return 0 if success else 1

if __name__ == '__main__':
    import sys
    sys.exit(main())
