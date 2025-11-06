#!/usr/bin/env python3
"""
批量Monitor输出生成脚本

功能：
1. 遍历 extracted_contracts 目录下所有包含 attack_state.json 的项目
2. 为每个项目调用 generate_monitor_output.py 生成Monitor分析
3. 支持并行处理、智能跳过、错误容错、进度显示
4. 生成详细的批处理报告

使用示例：
    # 处理所有项目
    python src/test/batch_generate_monitor.py

    # 只处理2024-01的项目
    python src/test/batch_generate_monitor.py --filter 2024-01

    # 测试模式：只处理前5个项目
    python src/test/batch_generate_monitor.py --limit 5

    # 强制重新生成（8个并行worker）
    python src/test/batch_generate_monitor.py --force --workers 8

    # 预览模式
    python src/test/batch_generate_monitor.py --dry-run

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
from multiprocessing import Pool, Manager, Lock
from dataclasses import dataclass
from datetime import datetime

# ============================================================================
# 配置
# ============================================================================

LOG_FORMAT = '%(asctime)s - [%(levelname)s] - %(message)s'
EXTRACTED_CONTRACTS_DIR = Path("extracted_contracts")
AUTOPATH_DIR = Path("autopath")
GENERATE_SCRIPT = Path("src/test/generate_monitor_output.py")

# Anvil端口配置（为并行worker分配不同端口）
BASE_ANVIL_PORT = 8545
MAX_WORKERS = 8

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ProjectInfo:
    """项目信息"""
    name: str
    path: Path
    attack_state_file: Path
    output_file: Path
    already_exists: bool

@dataclass
class ProcessResult:
    """处理结果"""
    project_name: str
    success: bool
    skipped: bool
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

        # 遍历所有子目录
        for year_month_dir in sorted(self.base_dir.iterdir()):
            if not year_month_dir.is_dir():
                continue

            # 应用过滤
            if filter_pattern and filter_pattern not in str(year_month_dir.name):
                continue

            # 遍历项目目录
            for project_dir in sorted(year_month_dir.iterdir()):
                if not project_dir.is_dir():
                    continue

                # 检查是否有 attack_state.json
                attack_state_file = project_dir / "attack_state.json"
                if not attack_state_file.exists():
                    continue

                # 构建输出文件路径
                project_name = project_dir.name
                output_file = self.autopath_dir / f"{project_name}_analysis.json"

                projects.append(ProjectInfo(
                    name=project_name,
                    path=project_dir,
                    attack_state_file=attack_state_file,
                    output_file=output_file,
                    already_exists=output_file.exists()
                ))

        return projects

    def should_skip(self, project: ProjectInfo, force: bool) -> bool:
        """
        判断项目是否应该跳过

        Args:
            project: 项目信息
            force: 是否强制重新生成

        Returns:
            是否跳过
        """
        if force:
            return False

        return project.already_exists

# ============================================================================
# 端口管理器
# ============================================================================

class PortManager:
    """管理Anvil端口分配，避免并行冲突"""

    def __init__(self, base_port: int = BASE_ANVIL_PORT, max_workers: int = MAX_WORKERS):
        self.base_port = base_port
        self.max_workers = max_workers
        self.ports = list(range(base_port, base_port + max_workers))

    def get_port(self, worker_id: int) -> int:
        """获取worker的专用端口"""
        return self.base_port + (worker_id % self.max_workers)

    def get_all_ports(self) -> List[int]:
        """获取所有端口"""
        return self.ports

# ============================================================================
# Worker进程函数
# ============================================================================

def process_project_worker(args: Tuple[ProjectInfo, int, int, str, bool, Path]) -> ProcessResult:
    """
    Worker进程函数：处理单个项目

    Args:
        args: (project_info, project_index, startup_delay, rpc_url, verbose, log_file)

    Returns:
        处理结果
    """
    project, project_index, startup_delay, rpc_url, verbose, log_file = args

    # 添加启动延迟，避免所有Anvil同时启动造成RPC并发过载
    if startup_delay > 0:
        time.sleep(startup_delay)

    start_time = time.time()

    # 使用项目索引作为端口偏移，确保每个项目使用独立端口
    anvil_port = BASE_ANVIL_PORT + project_index

    try:
        # 构建命令
        cmd = [
            "python",
            str(GENERATE_SCRIPT),
            "--project", str(project.path),
            "--rpc-url", rpc_url
        ]

        if verbose:
            cmd.append("--debug")

        # 设置环境变量（传递Anvil端口）
        env = os.environ.copy()
        env["ANVIL_PORT"] = str(anvil_port)

        # 执行命令
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10分钟超时
            env=env
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
            error_message="执行超时 (>10分钟)",
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
        workers: int = 4,
        rpc_url: str = "https://eth-mainnet.g.alchemy.com/v2/oKxs-03sij-U_N0iOlrSsZFr29-IqbuF",
        dry_run: bool = False,
        verbose: bool = False,
        log_file: Path = Path("batch_monitor.log")
    ):
        self.filter_pattern = filter_pattern
        self.limit = limit
        self.force = force
        self.workers = min(workers, MAX_WORKERS)
        self.rpc_url = rpc_url
        self.dry_run = dry_run
        self.verbose = verbose
        self.log_file = log_file

        self.scanner = ProjectScanner(EXTRACTED_CONTRACTS_DIR, AUTOPATH_DIR)
        self.port_manager = PortManager()

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
        self.logger.info("批处理Monitor输出生成 - 开始执行")
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

        # 2. 过滤和限制
        projects_to_process = []
        projects_to_skip = []

        for project in all_projects:
            if self.scanner.should_skip(project, self.force):
                projects_to_skip.append(project)
            else:
                projects_to_process.append(project)

        # 应用limit
        if self.limit and self.limit < len(projects_to_process):
            self.logger.info(f"应用限制: 只处理前 {self.limit} 个项目")
            projects_to_process = projects_to_process[:self.limit]

        self.logger.info(f"将要处理: {len(projects_to_process)}个")
        self.logger.info(f"将要跳过: {len(projects_to_skip)}个 (输出文件已存在)")

        # 3. Dry-run模式
        if self.dry_run:
            self._print_dry_run_summary(projects_to_process, projects_to_skip)
            return {'success': [], 'failed': [], 'skipped': []}

        # 4. 并行处理
        if not projects_to_process:
            self.logger.info("没有需要处理的项目")
            return {
                'success': [],
                'failed': [],
                'skipped': [p.name for p in projects_to_skip]
            }

        self.logger.info(f"开始并行处理 (workers={self.workers})...")
        self.logger.info(f"项目将使用端口: {BASE_ANVIL_PORT} 起（每个项目独立端口）")

        results = self._parallel_process(projects_to_process)

        # 5. 生成报告
        self._print_summary(results, projects_to_skip)

        return results

    def _parallel_process(self, projects: List[ProjectInfo]) -> Dict[str, List]:
        """并行处理项目"""
        results = {
            'success': [],
            'failed': [],
            'skipped': []
        }

        # 准备参数 - 计算启动延迟避免RPC并发过载
        worker_args = []
        for i, project in enumerate(projects):
            # 每个项目错开2秒启动，减少RPC并发压力
            # 前8个项目几乎同时启动（各延迟0.5秒）
            # 之后的项目延迟更长，等待前面的释放资源
            if i < self.workers:
                startup_delay = i * 0.5  # 前面的worker快速错开
            else:
                startup_delay = 2.0  # 后面的等待资源释放

            worker_args.append((
                project,
                i,  # 项目索引，用于端口分配
                startup_delay,  # 启动延迟
                self.rpc_url,
                self.verbose,
                self.log_file
            ))

        # 使用进程池并行处理
        start_time = time.time()

        try:
            with Pool(processes=self.workers) as pool:
                # 使用imap_unordered获取结果并显示进度
                total = len(worker_args)
                completed = 0

                for result in pool.imap_unordered(process_project_worker, worker_args):
                    completed += 1

                    # 处理结果
                    if result.skipped:
                        results['skipped'].append(result.project_name)
                        self.logger.info(f"⊘ [{completed}/{total}] {result.project_name} - 已跳过")
                    elif result.success:
                        results['success'].append(result.project_name)
                        self.logger.info(f"✓ [{completed}/{total}] {result.project_name} - 成功 ({result.duration:.1f}s)")
                    else:
                        results['failed'].append({
                            'project': result.project_name,
                            'error': result.error_message
                        })
                        self.logger.error(f"✗ [{completed}/{total}] {result.project_name} - 失败: {result.error_message}")

        except KeyboardInterrupt:
            self.logger.warning("收到中断信号，正在停止...")
            pool.terminate()
            pool.join()
            raise

        total_duration = time.time() - start_time
        self.logger.info(f"并行处理完成，总耗时: {total_duration:.1f}秒")

        return results

    def _print_dry_run_summary(self, to_process: List[ProjectInfo], to_skip: List[ProjectInfo]):
        """打印dry-run模式的摘要"""
        self.logger.info("\n" + "="*80)
        self.logger.info("预览模式 (--dry-run) - 不会实际执行")
        self.logger.info("="*80)

        self.logger.info(f"\n将要处理的项目 ({len(to_process)}个):")
        for i, project in enumerate(to_process, 1):
            self.logger.info(f"  {i}. {project.name}")
            self.logger.info(f"     路径: {project.path}")
            self.logger.info(f"     输出: {project.output_file}")

        if to_skip:
            self.logger.info(f"\n将要跳过的项目 ({len(to_skip)}个):")
            for i, project in enumerate(to_skip, 1):
                self.logger.info(f"  {i}. {project.name} (输出文件已存在)")

        self.logger.info("\n使用 --force 可以强制重新生成已存在的文件")
        self.logger.info("="*80)

    def _print_summary(self, results: Dict[str, List], skipped_projects: List[ProjectInfo]):
        """打印最终汇总报告"""
        self.logger.info("\n" + "="*80)
        self.logger.info("批处理执行报告")
        self.logger.info("="*80)

        success_count = len(results['success'])
        failed_count = len(results['failed'])
        skipped_count = len(skipped_projects)
        total = success_count + failed_count + skipped_count

        self.logger.info(f"\n结果汇总:")
        self.logger.info(f"  ✓ 成功: {success_count}项")
        self.logger.info(f"  ✗ 失败: {failed_count}项")
        self.logger.info(f"  ⊘ 跳过: {skipped_count}项 (已存在)")
        self.logger.info(f"  总计: {total}项")

        if results['success']:
            self.logger.info(f"\n成功项目 ({success_count}个):")
            for name in results['success']:
                self.logger.info(f"  ✓ {name}")

        if results['failed']:
            self.logger.info(f"\n失败项目 ({failed_count}个):")
            for item in results['failed']:
                self.logger.info(f"  ✗ {item['project']}")
                self.logger.info(f"     错误: {item['error']}")

        if skipped_projects:
            self.logger.info(f"\n跳过项目 ({skipped_count}个):")
            for project in skipped_projects[:5]:  # 只显示前5个
                self.logger.info(f"  ⊘ {project.name} (输出文件已存在)")
            if skipped_count > 5:
                self.logger.info(f"  ... 以及其他 {skipped_count - 5} 个项目")

        self.logger.info("\n" + "="*80)
        self.logger.info(f"详细日志已保存到: {self.log_file}")
        self.logger.info("="*80)

# ============================================================================
# 命令行接口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='批量生成Monitor输出文件',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 处理所有项目
  python src/test/batch_generate_monitor.py

  # 只处理2024-01的项目
  python src/test/batch_generate_monitor.py --filter 2024-01

  # 测试模式：只处理前5个项目
  python src/test/batch_generate_monitor.py --limit 5

  # 强制重新生成（8个并行worker）
  python src/test/batch_generate_monitor.py --force --workers 8

  # 预览模式
  python src/test/batch_generate_monitor.py --dry-run

  # 组合使用
  python src/test/batch_generate_monitor.py \\
    --filter 2024-03 \\
    --limit 10 \\
    --workers 6 \\
    --verbose
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
        help='强制重新生成，覆盖已存在的输出文件'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=4,
        help=f'并行worker数量（默认4，范围1-{MAX_WORKERS}）'
    )

    parser.add_argument(
        '--rpc-url',
        default='https://eth-mainnet.g.alchemy.com/v2/oKxs-03sij-U_N0iOlrSsZFr29-IqbuF',
        help='主网RPC URL（用于Anvil fork）'
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
        default=Path('batch_monitor.log'),
        help='日志输出文件（默认: batch_monitor.log）'
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
            rpc_url=args.rpc_url,
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
