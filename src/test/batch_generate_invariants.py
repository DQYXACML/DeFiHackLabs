#!/usr/bin/env python3
"""
批量不变量生成脚本

功能：
1. 遍历 extracted_contracts 目录下所有项目
2. 检查对应的 Monitor 分析输出（autopath/*_exp_analysis.json）
3. 为每个项目调用 generate_invariants_from_monitor.py 生成不变量
4. 支持并发处理、智能跳过、错误容错、进度显示
5. 生成详细的批处理报告

使用示例：
    # 处理所有项目
    python src/test/batch_generate_invariants.py

    # 只处理2024-01的项目
    python src/test/batch_generate_invariants.py --filter 2024-01

    # 测试模式：只处理前5个项目
    python src/test/batch_generate_invariants.py --limit 5

    # 强制重新生成（8个并行worker）
    python src/test/batch_generate_invariants.py --force --workers 8

    # 预览模式
    python src/test/batch_generate_invariants.py --dry-run

作者: Claude Code
版本: 1.0.0
"""

import os
import sys
import json
import time
import logging
import argparse
import traceback
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

# ============================================================================
# 配置
# ============================================================================

LOG_FORMAT = '%(asctime)s - [%(levelname)s] - %(message)s'
EXTRACTED_CONTRACTS_DIR = Path("extracted_contracts")
AUTOPATH_DIR = Path("autopath")
GENERATE_SCRIPT = Path("src/test/generate_invariants_from_monitor.py")

# 并发配置
MAX_WORKERS = 16  # Invariants 生成不需要 Anvil，可以更高并发

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ProjectInfo:
    """项目信息"""
    name: str                          # 项目名（如 BarleyFinance_exp）
    year_month: str                    # 时间段（如 2024-01）
    project_path: Path                 # extracted_contracts/2024-01/BarleyFinance_exp
    monitor_output: Path               # autopath/barleyfinance_exp_analysis.json
    invariants_output: Path            # .../BarleyFinance_exp/invariants.json
    monitor_exists: bool               # monitor-output 是否存在
    invariants_exists: bool            # invariants.json 是否已存在

@dataclass
class ProcessResult:
    """处理结果"""
    project_name: str
    success: bool
    skipped: bool
    skip_reason: Optional[str] = None  # 跳过原因
    error_message: Optional[str] = None
    duration: float = 0.0

# ============================================================================
# 项目扫描器
# ============================================================================

class ProjectScanner:
    """扫描并收集所有符合条件的项目"""

    def __init__(self, base_dir: Path, autopath_dir: Path):
        self.base_dir = base_dir
        self.autopath_dir = autopath_dir
        self.logger = logging.getLogger(self.__class__.__name__)

    def scan_projects(self, filter_pattern: Optional[str] = None) -> List[ProjectInfo]:
        """
        扫描所有项目

        Args:
            filter_pattern: 过滤模式（如 "2024-01"）

        Returns:
            项目信息列表
        """
        projects = []

        if not self.base_dir.exists():
            self.logger.error(f"基础目录不存在: {self.base_dir}")
            return projects

        # 遍历所有年月目录
        for year_month_dir in sorted(self.base_dir.iterdir()):
            if not year_month_dir.is_dir():
                continue

            # 应用过滤
            if filter_pattern and filter_pattern not in str(year_month_dir.name):
                continue

            year_month = year_month_dir.name

            # 遍历项目目录
            for project_dir in sorted(year_month_dir.iterdir()):
                if not project_dir.is_dir():
                    continue

                project_name = project_dir.name

                # 构建 monitor-output 路径（保持原始大小写）
                # 映射规则: BarleyFinance_exp → BarleyFinance_exp_analysis.json
                monitor_output = self.autopath_dir / f"{project_name}_analysis.json"

                # 构建 invariants 输出路径
                invariants_output = project_dir / "invariants.json"

                projects.append(ProjectInfo(
                    name=project_name,
                    year_month=year_month,
                    project_path=project_dir,
                    monitor_output=monitor_output,
                    invariants_output=invariants_output,
                    monitor_exists=monitor_output.exists(),
                    invariants_exists=invariants_output.exists()
                ))

        return projects

    def should_process(self, project: ProjectInfo, force: bool) -> Tuple[bool, Optional[str]]:
        """
        判断项目是否应该处理

        Args:
            project: 项目信息
            force: 是否强制重新生成

        Returns:
            (是否处理, 跳过原因)
        """
        # 1. 检查 monitor-output 是否存在
        if not project.monitor_exists:
            return False, f"Monitor 分析文件不存在: {project.monitor_output.name}"

        # 2. 检查 invariants.json 是否已存在
        if project.invariants_exists and not force:
            return False, "Invariants 文件已存在 (使用 --force 强制重新生成)"

        return True, None

# ============================================================================
# Worker 线程函数
# ============================================================================

def process_project_worker(args: Tuple[ProjectInfo, bool]) -> ProcessResult:
    """
    Worker 线程函数：处理单个项目

    Args:
        args: (project_info, verbose)

    Returns:
        处理结果
    """
    project, verbose = args

    start_time = time.time()

    try:
        # 构建命令
        cmd = [
            "python",
            str(GENERATE_SCRIPT),
            "--monitor-output", str(project.monitor_output),
            "--output", str(project.invariants_output),
            "--project", project.name
        ]

        if verbose:
            cmd.append("--debug")

        # 执行命令
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5分钟超时（Invariants 生成比 Monitor 快）
        )

        duration = time.time() - start_time

        if result.returncode == 0:
            return ProcessResult(
                project_name=project.name,
                success=True,
                skipped=False,
                duration=duration
            )
        else:
            error_msg = result.stderr[-500:] if result.stderr else "Unknown error"
            return ProcessResult(
                project_name=project.name,
                success=False,
                skipped=False,
                error_message=error_msg,
                duration=duration
            )

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        return ProcessResult(
            project_name=project.name,
            success=False,
            skipped=False,
            error_message="执行超时 (>5分钟)",
            duration=duration
        )

    except Exception as e:
        duration = time.time() - start_time
        return ProcessResult(
            project_name=project.name,
            success=False,
            skipped=False,
            error_message=f"{type(e).__name__}: {str(e)}",
            duration=duration
        )

# ============================================================================
# 批处理协调器
# ============================================================================

class BatchCoordinator:
    """批处理协调器：管理整个批处理流程"""

    def __init__(
        self,
        filter_pattern: Optional[str] = None,
        limit: Optional[int] = None,
        force: bool = False,
        workers: int = 8,
        dry_run: bool = False,
        verbose: bool = False,
        log_file: Path = Path("batch_invariants.log")
    ):
        self.filter_pattern = filter_pattern
        self.limit = limit
        self.force = force
        self.workers = min(workers, MAX_WORKERS)
        self.dry_run = dry_run
        self.verbose = verbose
        self.log_file = log_file

        self.scanner = ProjectScanner(EXTRACTED_CONTRACTS_DIR, AUTOPATH_DIR)

        # 配置日志
        self._setup_logging()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _setup_logging(self):
        """配置日志系统"""
        # 文件handler
        file_handler = logging.FileHandler(self.log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))

        # 控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter(LOG_FORMAT))

        # 配置root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        root_logger.handlers.clear()
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    def run(self) -> Dict[str, List]:
        """
        执行批处理

        Returns:
            结果字典 {'success': [...], 'failed': [...], 'skipped': [...]}
        """
        self.logger.info("="*80)
        self.logger.info("批处理不变量生成 - 开始执行")
        self.logger.info("="*80)

        # 1. 扫描项目
        self.logger.info(f"扫描路径: {EXTRACTED_CONTRACTS_DIR}")
        if self.filter_pattern:
            self.logger.info(f"过滤条件: {self.filter_pattern}")

        all_projects = self.scanner.scan_projects(self.filter_pattern)
        self.logger.info(f"找到项目: {len(all_projects)}个")

        if not all_projects:
            self.logger.warning("未找到任何符合条件的项目")
            return {'success': [], 'failed': [], 'skipped': []}

        # 2. 过滤和分类
        projects_to_process = []
        projects_to_skip = []

        for project in all_projects:
            should_process, skip_reason = self.scanner.should_process(project, self.force)

            if should_process:
                projects_to_process.append(project)
            else:
                projects_to_skip.append((project, skip_reason))

        # 应用limit
        if self.limit and self.limit < len(projects_to_process):
            self.logger.info(f"应用限制: 只处理前 {self.limit} 个项目")
            projects_to_process = projects_to_process[:self.limit]

        self.logger.info(f"将要处理: {len(projects_to_process)}个")
        self.logger.info(f"将要跳过: {len(projects_to_skip)}个")

        # 统计跳过原因
        skip_reasons = {}
        for _, reason in projects_to_skip:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

        if skip_reasons:
            self.logger.info("跳过原因统计:")
            for reason, count in skip_reasons.items():
                self.logger.info(f"  - {reason}: {count}个")

        # 3. Dry-run模式
        if self.dry_run:
            self._print_dry_run_summary(projects_to_process, projects_to_skip)
            return {'success': [], 'failed': [], 'skipped': []}

        # 4. 并发处理
        if not projects_to_process:
            self.logger.info("没有需要处理的项目")
            return {
                'success': [],
                'failed': [],
                'skipped': [{'project': p.name, 'reason': r} for p, r in projects_to_skip]
            }

        self.logger.info(f"开始并发处理 (workers={self.workers})...")

        results = self._parallel_process(projects_to_process)

        # 添加预先跳过的项目到结果
        for project, reason in projects_to_skip:
            results['skipped'].append({
                'project': project.name,
                'reason': reason
            })

        # 5. 生成报告
        self._print_summary(results)

        return results

    def _parallel_process(self, projects: List[ProjectInfo]) -> Dict[str, List]:
        """并发处理项目"""
        results = {
            'success': [],
            'failed': [],
            'skipped': []
        }

        # 准备参数
        worker_args = [(project, self.verbose) for project in projects]

        # 使用线程池并发处理（Invariants 生成是 CPU 密集型，但调用的是外部 Python 进程，所以用线程即可）
        start_time = time.time()
        total = len(worker_args)
        completed = 0

        try:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                # 提交所有任务
                future_to_project = {
                    executor.submit(process_project_worker, args): args[0]
                    for args in worker_args
                }

                # 处理完成的任务
                for future in as_completed(future_to_project):
                    project = future_to_project[future]
                    completed += 1

                    try:
                        result = future.result()

                        # 处理结果
                        if result.skipped:
                            results['skipped'].append({
                                'project': result.project_name,
                                'reason': result.skip_reason
                            })
                            self.logger.info(f"⊘ [{completed}/{total}] {result.project_name} - 已跳过: {result.skip_reason}")
                        elif result.success:
                            results['success'].append(result.project_name)
                            self.logger.info(f"✓ [{completed}/{total}] {result.project_name} - 成功 ({result.duration:.1f}s)")
                        else:
                            results['failed'].append({
                                'project': result.project_name,
                                'error': result.error_message
                            })
                            self.logger.error(f"✗ [{completed}/{total}] {result.project_name} - 失败: {result.error_message}")

                    except Exception as e:
                        results['failed'].append({
                            'project': project.name,
                            'error': f"处理异常: {str(e)}"
                        })
                        self.logger.error(f"✗ [{completed}/{total}] {project.name} - 异常: {e}")

        except KeyboardInterrupt:
            self.logger.warning("收到中断信号，正在停止...")
            raise

        total_duration = time.time() - start_time
        self.logger.info(f"并发处理完成，总耗时: {total_duration:.1f}秒")

        return results

    def _print_dry_run_summary(self, to_process: List[ProjectInfo], to_skip: List[Tuple[ProjectInfo, str]]):
        """打印dry-run模式的摘要"""
        self.logger.info("\n" + "="*80)
        self.logger.info("预览模式 (--dry-run) - 不会实际执行")
        self.logger.info("="*80)

        self.logger.info(f"\n将要处理的项目 ({len(to_process)}个):")
        for i, project in enumerate(to_process, 1):
            self.logger.info(f"  {i}. {project.name} ({project.year_month})")
            self.logger.info(f"     Monitor输入: {project.monitor_output.name}")
            self.logger.info(f"     输出路径: {project.invariants_output}")

        if to_skip:
            self.logger.info(f"\n将要跳过的项目 ({len(to_skip)}个):")
            skip_count_by_reason = {}
            for project, reason in to_skip:
                skip_count_by_reason[reason] = skip_count_by_reason.get(reason, 0) + 1

            for reason, count in skip_count_by_reason.items():
                self.logger.info(f"  {reason}: {count}个")

        self.logger.info("\n提示:")
        self.logger.info("  • 使用 --force 强制重新生成已存在的文件")
        self.logger.info("  • 使用 --filter 2024-01 仅处理特定时间段")
        self.logger.info("  • 使用 --limit 10 限制处理数量（测试用）")
        self.logger.info("="*80)

    def _print_summary(self, results: Dict[str, List]):
        """打印最终汇总报告"""
        self.logger.info("\n" + "="*80)
        self.logger.info("批处理执行报告")
        self.logger.info("="*80)

        success_count = len(results['success'])
        failed_count = len(results['failed'])
        skipped_count = len(results['skipped'])
        total = success_count + failed_count + skipped_count

        self.logger.info(f"\n结果汇总:")
        self.logger.info(f"  ✓ 成功: {success_count}项")
        self.logger.info(f"  ✗ 失败: {failed_count}项")
        self.logger.info(f"  ⊘ 跳过: {skipped_count}项")
        self.logger.info(f"  总计: {total}项")

        if results['success']:
            self.logger.info(f"\n成功项目 ({success_count}个):")
            for name in results['success'][:10]:  # 只显示前10个
                self.logger.info(f"  ✓ {name}")
            if success_count > 10:
                self.logger.info(f"  ... 以及其他 {success_count - 10} 个项目")

        if results['failed']:
            self.logger.info(f"\n失败项目 ({failed_count}个):")
            for item in results['failed']:
                self.logger.info(f"  ✗ {item['project']}")
                # 截断错误消息
                error = item['error']
                if len(error) > 100:
                    error = error[:100] + "..."
                self.logger.info(f"     错误: {error}")

        if results['skipped']:
            # 统计跳过原因
            skip_reasons = {}
            for item in results['skipped']:
                reason = item['reason']
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

            self.logger.info(f"\n跳过项目统计 ({skipped_count}个):")
            for reason, count in skip_reasons.items():
                self.logger.info(f"  ⊘ {reason}: {count}个")

        self.logger.info("\n" + "="*80)
        self.logger.info(f"详细日志已保存到: {self.log_file}")
        self.logger.info("="*80)

# ============================================================================
# 命令行接口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='批量生成不变量文件（从 Monitor 输出）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 处理所有项目
  python src/test/batch_generate_invariants.py

  # 只处理2024-01的项目
  python src/test/batch_generate_invariants.py --filter 2024-01

  # 测试模式：只处理前5个项目
  python src/test/batch_generate_invariants.py --limit 5

  # 强制重新生成（16个并行worker）
  python src/test/batch_generate_invariants.py --force --workers 16

  # 预览模式
  python src/test/batch_generate_invariants.py --dry-run

  # 组合使用
  python src/test/batch_generate_invariants.py \\
    --filter 2024 \\
    --limit 20 \\
    --workers 12 \\
    --verbose

注意事项:
  • Monitor 分析文件命名规则: ProjectName_exp → {projectname}_exp_analysis.json (全部转小写)
  • 如果 Monitor 分析文件不存在，该项目会被自动跳过
  • 使用 --force 可以强制重新生成已存在的 invariants.json
  • 推荐 worker 数: 8-16（Invariants 生成速度快，可以更高并发）
        """
    )

    parser.add_argument(
        '--filter',
        help='过滤模式（如 "2024-01" 只处理该月份的项目）'
    )

    parser.add_argument(
        '--limit',
        type=int,
        help='限制处理的项目数量（如 --limit 10）'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='强制重新生成，覆盖已存在的 invariants.json'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=8,
        help=f'并发worker数量（默认8，范围1-{MAX_WORKERS}）'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='预览模式，只显示将要处理的项目列表，不实际执行'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='详细日志模式'
    )

    parser.add_argument(
        '--log-file',
        type=Path,
        default=Path('batch_invariants.log'),
        help='日志输出文件（默认: batch_invariants.log）'
    )

    args = parser.parse_args()

    # 验证参数
    if args.workers < 1 or args.workers > MAX_WORKERS:
        print(f"错误: workers 必须在 1-{MAX_WORKERS} 范围内")
        return 1

    if args.limit and args.limit < 1:
        print("错误: limit 必须大于0")
        return 1

    # 创建协调器并运行
    try:
        coordinator = BatchCoordinator(
            filter_pattern=args.filter,
            limit=args.limit,
            force=args.force,
            workers=args.workers,
            dry_run=args.dry_run,
            verbose=args.verbose,
            log_file=args.log_file
        )

        results = coordinator.run()

        # 返回退出码
        if results['failed']:
            return 1  # 有失败的项目
        else:
            return 0  # 全部成功

    except KeyboardInterrupt:
        print("\n\n用户中断执行")
        return 130

    except Exception as e:
        print(f"\n致命错误: {e}")
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
