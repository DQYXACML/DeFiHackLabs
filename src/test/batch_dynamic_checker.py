#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量动态检测协调器

功能：
- 并行处理多个攻击的动态检测
- 端口管理（每个worker独立Anvil端口）
- 进度跟踪
- 失败容错
- 生成汇总报告
"""

import argparse
import logging
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class AttackInfo:
    """攻击信息"""
    event_name: str
    year_month: str
    has_invariants: bool
    has_attack_state: bool
    has_script: bool


@dataclass
class CheckResult:
    """检测结果"""
    event_name: str
    year_month: str
    status: str  # 'Success', 'Failed', 'Skipped'
    total_invariants: int = 0
    violations: int = 0
    passed: int = 0
    violation_rate: float = 0.0
    error_message: str = ''
    timestamp: str = ''
    duration_seconds: float = 0.0


class BatchDynamicChecker:
    """批量动态检测协调器"""

    def __init__(
        self,
        workers: int = 4,
        base_port: int = 8545,
        skip_monitor: bool = False,
        output_dir: Path = Path("reports/batch_dynamic")
    ):
        """
        初始化批量检测器

        Args:
            workers: 并发worker数量
            base_port: 基础端口（每个worker使用 base_port + worker_id）
            skip_monitor: 跳过Monitor分析
            output_dir: 输出目录
        """
        self.workers = workers
        self.base_port = base_port
        self.skip_monitor = skip_monitor
        self.output_dir = output_dir

        # 项目路径
        self.project_root = Path(__file__).parent.parent.parent
        self.src_test_dir = self.project_root / "src" / "test"
        self.extracted_dir = self.project_root / "extracted_contracts"

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        filter_year_month: Optional[str] = None,
        event_names: Optional[List[str]] = None
    ) -> List[CheckResult]:
        """
        运行批量检测

        Args:
            filter_year_month: 过滤特定年月（如 '2024-01'）
            event_names: 指定要检测的攻击列表

        Returns:
            检测结果列表
        """
        logger.info(f"{'='*70}")
        logger.info(f"批量动态检测开始")
        logger.info(f"{'='*70}")
        logger.info(f"Workers: {self.workers}")
        logger.info(f"端口范围: {self.base_port}-{self.base_port + self.workers - 1}")
        logger.info(f"跳过Monitor: {self.skip_monitor}")

        # 扫描攻击
        attacks = self._scan_attacks(filter_year_month, event_names)

        if not attacks:
            logger.warning("未找到符合条件的攻击")
            return []

        logger.info(f"\n找到 {len(attacks)} 个可检测的攻击")

        # 并行处理
        results = self._parallel_process(attacks)

        # 生成汇总报告
        self._generate_summary(results)

        logger.info(f"\n{'='*70}")
        logger.info(f"批量检测完成!")
        logger.info(f"{'='*70}")

        return results

    def _scan_attacks(
        self,
        filter_year_month: Optional[str],
        event_names: Optional[List[str]]
    ) -> List[AttackInfo]:
        """扫描可检测的攻击"""
        logger.info("\n扫描攻击...")

        attacks = []

        # 遍历extracted_contracts目录
        if not self.extracted_dir.exists():
            logger.error(f"extracted_contracts目录不存在: {self.extracted_dir}")
            return attacks

        for year_month_dir in self.extracted_dir.iterdir():
            if not year_month_dir.is_dir():
                continue

            year_month = year_month_dir.name

            # 过滤年月
            if filter_year_month and year_month != filter_year_month:
                continue

            for attack_dir in year_month_dir.iterdir():
                if not attack_dir.is_dir():
                    continue

                event_name = attack_dir.name

                # 过滤事件名
                if event_names and event_name not in event_names:
                    continue

                # 检查必需文件
                attack_state_file = attack_dir / "attack_state.json"
                invariants_file = attack_dir / "invariants.json"
                attack_script = self.src_test_dir / year_month / f"{event_name}.sol"

                has_state = attack_state_file.exists()
                has_invariants = invariants_file.exists()
                has_script = attack_script.exists()

                # 只处理同时有状态、不变量和脚本的攻击
                if has_state and has_invariants and has_script:
                    attacks.append(AttackInfo(
                        event_name=event_name,
                        year_month=year_month,
                        has_invariants=has_invariants,
                        has_attack_state=has_state,
                        has_script=has_script
                    ))
                    logger.info(f"  ✓ {year_month}/{event_name}")
                else:
                    logger.debug(f"  ✗ {year_month}/{event_name} (缺少文件: "
                                 f"state={has_state}, inv={has_invariants}, script={has_script})")

        return attacks

    def _parallel_process(self, attacks: List[AttackInfo]) -> List[CheckResult]:
        """并行处理攻击"""
        logger.info(f"\n开始并行处理（{self.workers} workers）...\n")

        results = []

        # 使用进程池
        with ProcessPoolExecutor(max_workers=self.workers) as executor:
            # 提交所有任务
            future_to_attack = {}

            for i, attack in enumerate(attacks):
                # 为每个worker分配独立端口
                worker_id = i % self.workers
                anvil_port = self.base_port + worker_id

                future = executor.submit(
                    run_single_check,
                    attack.event_name,
                    attack.year_month,
                    anvil_port,
                    self.skip_monitor,
                    self.output_dir
                )

                future_to_attack[future] = attack

            # 处理完成的任务
            completed = 0
            total = len(attacks)

            for future in as_completed(future_to_attack):
                attack = future_to_attack[future]
                completed += 1

                try:
                    result = future.result(timeout=600)  # 10分钟超时
                    results.append(result)

                    status_icon = "✅" if result.status == 'Success' else "❌"
                    logger.info(f"[{completed}/{total}] {status_icon} {result.event_name} - "
                                f"{result.violations} violations / {result.total_invariants} invariants")

                except Exception as e:
                    logger.error(f"[{completed}/{total}] ❌ {attack.event_name} - 异常: {e}")

                    results.append(CheckResult(
                        event_name=attack.event_name,
                        year_month=attack.year_month,
                        status='Failed',
                        error_message=str(e),
                        timestamp=datetime.now().isoformat()
                    ))

        return results

    def _generate_summary(self, results: List[CheckResult]):
        """生成汇总报告"""
        logger.info("\n生成汇总报告...")

        # 准备数据
        summary_data = []

        for result in results:
            summary_data.append({
                'event_name': result.event_name,
                'year_month': result.year_month,
                'total_invariants': result.total_invariants,
                'violations': result.violations,
                'passed': result.passed,
                'violation_rate': result.violation_rate,
                'status': result.status,
                'timestamp': result.timestamp
            })

        # 使用ReportBuilder生成汇总
        from report_builder import ReportBuilder

        ReportBuilder.generate_batch_summary(
            results=summary_data,
            output_dir=self.output_dir
        )

        # 打印统计
        logger.info(f"\n{'='*70}")
        logger.info("批量检测统计:")
        logger.info(f"  总攻击数: {len(results)}")
        logger.info(f"  成功: {len([r for r in results if r.status == 'Success'])}")
        logger.info(f"  失败: {len([r for r in results if r.status == 'Failed'])}")
        logger.info(f"  总违规数: {sum(r.violations for r in results)}")
        logger.info(f"  总不变量数: {sum(r.total_invariants for r in results)}")
        logger.info(f"{'='*70}")


def run_single_check(
    event_name: str,
    year_month: str,
    anvil_port: int,
    skip_monitor: bool,
    output_dir: Path
) -> CheckResult:
    """
    运行单个攻击的检测（在独立进程中）

    Args:
        event_name: 攻击名称
        year_month: 年月
        anvil_port: Anvil端口
        skip_monitor: 跳过Monitor
        output_dir: 输出目录

    Returns:
        CheckResult
    """
    start_time = time.time()

    try:
        # 导入动态检测器
        from dynamic_invariant_checker import DynamicInvariantChecker

        # 创建检测器
        checker = DynamicInvariantChecker(
            event_name=event_name,
            year_month=year_month,
            anvil_port=anvil_port,
            skip_monitor=skip_monitor,
            output_dir=output_dir
        )

        # 运行检测
        success = checker.run()

        duration = time.time() - start_time

        if not success:
            return CheckResult(
                event_name=event_name,
                year_month=year_month,
                status='Failed',
                error_message='Checker returned False',
                timestamp=datetime.now().isoformat(),
                duration_seconds=duration
            )

        # 提取结果
        violations = [r for r in checker.violation_results if r.violated]

        return CheckResult(
            event_name=event_name,
            year_month=year_month,
            status='Success',
            total_invariants=len(checker.violation_results),
            violations=len(violations),
            passed=len(checker.violation_results) - len(violations),
            violation_rate=len(violations) / len(checker.violation_results) * 100 if checker.violation_results else 0,
            timestamp=datetime.now().isoformat(),
            duration_seconds=duration
        )

    except Exception as e:
        duration = time.time() - start_time

        return CheckResult(
            event_name=event_name,
            year_month=year_month,
            status='Failed',
            error_message=str(e),
            timestamp=datetime.now().isoformat(),
            duration_seconds=duration
        )


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='批量动态不变量检测器')

    parser.add_argument('--filter', type=str, help='过滤年月（如 2024-01）')
    parser.add_argument('--events', type=str, help='指定攻击列表（逗号分隔，如 BarleyFinance_exp,Gamma_exp）')
    parser.add_argument('--workers', type=int, default=4, help='并发worker数量（默认4）')
    parser.add_argument('--base-port', type=int, default=8545, help='基础Anvil端口（默认8545）')
    parser.add_argument('--skip-monitor', action='store_true', help='跳过Monitor分析')
    parser.add_argument('--output-dir', type=Path, default=Path('reports/batch_dynamic'),
                        help='报告输出目录')

    args = parser.parse_args()

    # 解析事件列表
    event_names = None
    if args.events:
        event_names = [e.strip() for e in args.events.split(',')]

    # 创建批量检测器
    checker = BatchDynamicChecker(
        workers=args.workers,
        base_port=args.base_port,
        skip_monitor=args.skip_monitor,
        output_dir=args.output_dir
    )

    # 运行检测
    results = checker.run(
        filter_year_month=args.filter,
        event_names=event_names
    )

    # 根据结果决定退出码
    failed = len([r for r in results if r.status == 'Failed'])
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
