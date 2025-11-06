#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态不变量检测器

完整的端到端不变量检测流程：
1. 加载attack_state.json和invariants.json
2. 启动Anvil
3. 部署状态到Anvil
4. 拍摄存储快照(Before)
5. 执行forge test攻击脚本
6. 提取攻击交易hash
7. 拍摄存储快照(After)
8. 调用Go Monitor分析交易trace (可选)
9. 对比存储变化
10. 评估所有不变量
11. 生成报告
12. 清理Anvil
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 导入现有工具
sys.path.append(str(Path(__file__).parent))

from anvil_utils import AnvilManager
from deploy_to_anvil import deploy_to_anvil
from storage_comparator import StorageComparator
from runtime_metrics_extractor import RuntimeMetricsExtractor
from invariant_evaluator import InvariantEvaluator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DynamicInvariantChecker:
    """动态不变量检测器"""

    def __init__(
        self,
        event_name: str,
        year_month: str,
        anvil_port: int = 8545,
        skip_monitor: bool = False,
        output_dir: Path = Path("reports/dynamic_checks")
    ):
        """
        初始化检测器

        Args:
            event_name: 攻击事件名称（如 BarleyFinance_exp）
            year_month: 年月目录（如 2024-01）
            anvil_port: Anvil端口
            skip_monitor: 跳过Monitor分析
            output_dir: 报告输出目录
        """
        self.event_name = event_name
        self.year_month = year_month
        self.anvil_port = anvil_port
        self.skip_monitor = skip_monitor
        self.output_dir = output_dir

        # 路径配置
        self.project_root = Path(__file__).parent.parent.parent
        self.extracted_dir = self.project_root / "extracted_contracts" / year_month / event_name
        self.attack_script = self.project_root / "src" / "test" / year_month / f"{event_name}.sol"

        # 文件路径
        self.attack_state_file = self.extracted_dir / "attack_state.json"
        self.invariants_file = self.extracted_dir / "invariants.json"

        # RPC URL
        self.rpc_url = f"http://127.0.0.1:{anvil_port}"

        # 工具实例
        self.storage_comparator = StorageComparator(rpc_url=self.rpc_url)
        self.metrics_extractor = RuntimeMetricsExtractor()
        self.invariant_evaluator = InvariantEvaluator()

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 结果数据
        self.attack_tx_hash: Optional[str] = None
        self.invariants: List[Dict] = []
        self.storage_changes: Dict = {}
        self.runtime_metrics: Optional[Dict] = None
        self.violation_results: List = []

    def run(self) -> bool:
        """
        运行完整的检测流程

        Returns:
            是否成功完成检测
        """
        logger.info(f"{'='*70}")
        logger.info(f"开始动态检测: {self.event_name}")
        logger.info(f"{'='*70}")

        try:
            # 步骤1: 加载数据
            if not self._load_data():
                return False

            # 步骤2: 启动Anvil
            anvil = self._start_anvil()
            if not anvil:
                return False

            try:
                # 步骤3: 部署状态
                if not self._deploy_state():
                    return False

                # 步骤4: 拍摄前快照
                snapshot_before = self._capture_before_snapshot()

                # 步骤5: 执行攻击
                if not self._execute_attack():
                    return False

                # 步骤6: 拍摄后快照
                snapshot_after = self._capture_after_snapshot()

                # 步骤7: 对比存储变化
                self.storage_changes = self.storage_comparator.compare_snapshots(
                    snapshot_before,
                    snapshot_after
                )

                # 步骤8: 提取运行时指标
                if not self.skip_monitor:
                    self._extract_runtime_metrics()

                # 步骤9: 评估不变量
                self._evaluate_invariants()

                # 步骤10: 生成报告
                self._generate_report()

                logger.info(f"\n{'='*70}")
                logger.info(f"检测完成！报告已保存到: {self.output_dir}")
                logger.info(f"{'='*70}\n")

                return True

            finally:
                # 步骤11: 清理Anvil
                logger.info("清理Anvil...")
                anvil.stop()

        except Exception as e:
            logger.error(f"检测过程中出现异常: {e}", exc_info=True)
            return False

    # ==================== 内部方法 ====================

    def _load_data(self) -> bool:
        """加载attack_state和invariants"""
        logger.info("步骤1: 加载数据文件...")

        # 检查文件是否存在
        if not self.attack_state_file.exists():
            logger.error(f"attack_state.json不存在: {self.attack_state_file}")
            return False

        if not self.invariants_file.exists():
            logger.error(f"invariants.json不存在: {self.invariants_file}")
            return False

        if not self.attack_script.exists():
            logger.error(f"攻击脚本不存在: {self.attack_script}")
            return False

        # 加载invariants
        try:
            with open(self.invariants_file, 'r') as f:
                invariants_data = json.load(f)
                self.invariants = invariants_data.get('storage_invariants', []) + \
                                  invariants_data.get('runtime_invariants', [])

            logger.info(f"  ✓ 加载了 {len(self.invariants)} 个不变量")

        except Exception as e:
            logger.error(f"加载invariants失败: {e}")
            return False

        return True

    def _start_anvil(self) -> Optional[AnvilManager]:
        """启动Anvil"""
        logger.info(f"步骤2: 启动Anvil (端口 {self.anvil_port})...")

        anvil = AnvilManager(port=self.anvil_port)

        if not anvil.start(timeout=30):
            logger.error("Anvil启动失败")
            return None

        logger.info("  ✓ Anvil启动成功")
        time.sleep(1)

        return anvil

    def _deploy_state(self) -> bool:
        """部署状态到Anvil"""
        logger.info("步骤3: 部署状态到Anvil...")

        try:
            deploy_to_anvil(
                state_file=self.attack_state_file,
                rpc_url=self.rpc_url
            )

            logger.info("  ✓ 状态部署成功")
            return True

        except Exception as e:
            logger.error(f"部署状态失败: {e}")
            return False

    def _capture_before_snapshot(self) -> Dict:
        """拍摄攻击前的存储快照"""
        logger.info("步骤4: 拍摄攻击前存储快照...")

        # 从不变量中提取需要监控的存储槽
        slots = self.storage_comparator.extract_slots_from_invariants(self.invariants)

        logger.info(f"  监控 {len(slots)} 个存储槽")

        snapshot = self.storage_comparator.capture_snapshot(
            contracts_and_slots=slots,
            include_balances=True
        )

        logger.info(f"  ✓ 快照捕获成功")

        return snapshot

    def _execute_attack(self) -> bool:
        """执行攻击脚本"""
        logger.info("步骤5: 执行攻击脚本...")

        try:
            # 运行forge test
            result = subprocess.run(
                [
                    'forge', 'test',
                    '--match-path', str(self.attack_script),
                    '--rpc-url', self.rpc_url,
                    '--skip', 'src/test/2024-11/proxy_b7e1_exp.sol',
                    '--skip', 'src/test/2025-05/Corkprotocol_exp.sol',
                    '-vvv'
                ],
                capture_output=True,
                text=True,
                timeout=180
            )

            if result.returncode != 0:
                logger.error(f"forge test执行失败:\n{result.stderr}")
                return False

            logger.info("  ✓ 攻击脚本执行成功")

            # 提取交易hash
            self.attack_tx_hash = self._extract_tx_hash()

            if self.attack_tx_hash:
                logger.info(f"  交易hash: {self.attack_tx_hash}")
            else:
                logger.warning("  未能提取交易hash")

            return True

        except subprocess.TimeoutExpired:
            logger.error("forge test执行超时")
            return False
        except Exception as e:
            logger.error(f"执行攻击脚本异常: {e}")
            return False

    def _capture_after_snapshot(self) -> Dict:
        """拍摄攻击后的存储快照"""
        logger.info("步骤6: 拍摄攻击后存储快照...")

        # 使用相同的槽位
        slots = self.storage_comparator.extract_slots_from_invariants(self.invariants)

        snapshot = self.storage_comparator.capture_snapshot(
            contracts_and_slots=slots,
            include_balances=True
        )

        logger.info("  ✓ 快照捕获成功")

        return snapshot

    def _extract_tx_hash(self) -> Optional[str]:
        """提取攻击交易的hash"""
        try:
            # 获取最近的区块
            result = subprocess.run(
                ['cast', 'block-number', '--rpc-url', self.rpc_url],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return None

            latest_block = int(result.stdout.strip())

            # 查找最近5个区块中gas使用最高的交易
            max_gas = 0
            target_tx = None

            for block_num in range(max(0, latest_block - 5), latest_block + 1):
                # 获取区块
                result = subprocess.run(
                    ['cast', 'block', str(block_num), '--json', '--rpc-url', self.rpc_url],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode != 0:
                    continue

                block = json.loads(result.stdout)
                transactions = block.get('transactions', [])

                for tx_hash in transactions:
                    # 获取交易receipt
                    result = subprocess.run(
                        ['cast', 'receipt', tx_hash, '--json', '--rpc-url', self.rpc_url],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )

                    if result.returncode != 0:
                        continue

                    receipt = json.loads(result.stdout)
                    gas_used = int(receipt.get('gasUsed', '0x0'), 16)

                    # 找gas最高的交易（通常是攻击交易）
                    if gas_used > max_gas and gas_used > 100000:
                        max_gas = gas_used
                        target_tx = tx_hash

            return target_tx

        except Exception as e:
            logger.error(f"提取交易hash失败: {e}")
            return None

    def _extract_runtime_metrics(self):
        """提取运行时指标"""
        if not self.attack_tx_hash:
            logger.warning("未找到交易hash，跳过运行时指标提取")
            return

        logger.info("步骤7: 提取运行时指标...")

        try:
            # 方法1: 使用Go Monitor（如果可用）
            monitor_output = self.output_dir / f"{self.event_name}_monitor.json"

            metrics = self.metrics_extractor.run_monitor_and_extract(
                tx_hash=self.attack_tx_hash,
                rpc_url=self.rpc_url,
                config_file=self.invariants_file,
                output_file=monitor_output
            )

            # 如果Monitor失败，回退到trace分析
            if metrics.gas_used == 0:
                logger.info("  Monitor未返回数据，回退到trace分析...")
                metrics = self.metrics_extractor.extract_from_trace(
                    tx_hash=self.attack_tx_hash,
                    rpc_url=self.rpc_url
                )

            self.runtime_metrics = metrics.to_dict()

            logger.info(f"  ✓ 运行时指标提取成功")
            logger.info(f"    - Gas使用: {metrics.gas_used}")
            logger.info(f"    - 调用深度: {metrics.call_depth}")
            logger.info(f"    - 重入深度: {metrics.reentrancy_depth}")
            logger.info(f"    - 循环迭代: {metrics.loop_iterations}")

        except Exception as e:
            logger.error(f"提取运行时指标失败: {e}")
            self.runtime_metrics = {}

    def _evaluate_invariants(self):
        """评估所有不变量"""
        logger.info("步骤8: 评估不变量...")

        self.violation_results = self.invariant_evaluator.evaluate_all(
            invariants=self.invariants,
            storage_changes=self.storage_changes,
            runtime_metrics=self.runtime_metrics
        )

        # 统计违规情况
        violations = [r for r in self.violation_results if r.violated]

        logger.info(f"  ✓ 评估完成")
        logger.info(f"    - 总不变量数: {len(self.violation_results)}")
        logger.info(f"    - 违规数量: {len(violations)}")
        logger.info(f"    - 通过数量: {len(self.violation_results) - len(violations)}")

        # 显示违规详情
        if violations:
            logger.warning(f"\n  检测到 {len(violations)} 个不变量违规:")
            for v in violations:
                logger.warning(f"    ❌ [{v.invariant_id}] {v.invariant_type} - {v.description}")
                logger.warning(f"       阈值: {v.threshold}, 实际: {v.actual_value}")

    def _generate_report(self):
        """生成报告"""
        logger.info("步骤9: 生成报告...")

        # 导入report_builder（将在下一步创建）
        try:
            from report_builder import ReportBuilder

            builder = ReportBuilder(
                event_name=self.event_name,
                year_month=self.year_month,
                output_dir=self.output_dir
            )

            builder.build_report(
                invariants=self.invariants,
                violation_results=self.violation_results,
                storage_changes=self.storage_changes,
                runtime_metrics=self.runtime_metrics,
                attack_tx_hash=self.attack_tx_hash
            )

            logger.info("  ✓ 报告生成成功")

        except ImportError:
            # 如果report_builder还未创建，生成简单报告
            logger.warning("report_builder未找到，生成简单JSON报告...")
            self._generate_simple_report()

    def _generate_simple_report(self):
        """生成简单的JSON报告"""
        report = {
            'event_name': self.event_name,
            'year_month': self.year_month,
            'attack_tx_hash': self.attack_tx_hash,
            'total_invariants': len(self.violation_results),
            'violations_detected': len([r for r in self.violation_results if r.violated]),
            'violation_results': [
                {
                    'invariant_id': r.invariant_id,
                    'invariant_type': r.invariant_type,
                    'severity': r.severity.value,
                    'violated': r.violated,
                    'threshold': str(r.threshold),
                    'actual_value': str(r.actual_value),
                    'description': r.description,
                    'impact': r.impact,
                    'evidence': r.evidence
                }
                for r in self.violation_results
            ]
        }

        report_file = self.output_dir / f"{self.event_name}_report.json"

        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)

        logger.info(f"  简单报告已保存: {report_file}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='动态不变量检测器')

    parser.add_argument('--event-name', required=True, help='攻击事件名称（如 BarleyFinance_exp）')
    parser.add_argument('--year-month', required=True, help='年月目录（如 2024-01）')
    parser.add_argument('--anvil-port', type=int, default=8545, help='Anvil端口（默认8545）')
    parser.add_argument('--skip-monitor', action='store_true', help='跳过Monitor分析')
    parser.add_argument('--output-dir', type=Path, default=Path('reports/dynamic_checks'),
                        help='报告输出目录')

    args = parser.parse_args()

    # 创建检测器
    checker = DynamicInvariantChecker(
        event_name=args.event_name,
        year_month=args.year_month,
        anvil_port=args.anvil_port,
        skip_monitor=args.skip_monitor,
        output_dir=args.output_dir
    )

    # 运行检测
    success = checker.run()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
