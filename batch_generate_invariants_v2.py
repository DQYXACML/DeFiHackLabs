#!/usr/bin/env python3
"""
批量生成不变量 - v2.0版本

使用InvariantGeneratorV2系统批量生成高质量DeFi协议不变量。

特性:
- 支持before/after状态差异分析
- 协议类型自动检测(90%+准确率)
- 攻击模式识别(10种模式)
- 业务逻辑不变量生成(18+模板)
- 跨合约关系分析
- 并行处理

用法:
    # 处理所有2024-01协议
    python batch_generate_invariants_v2.py --filter 2024-01

    # 并行处理
    python batch_generate_invariants_v2.py --filter 2024-01 --workers 8

    # 预览模式
    python batch_generate_invariants_v2.py --filter 2024-01 --dry-run

    # 强制重新生成
    python batch_generate_invariants_v2.py --filter 2024-01 --force

作者: Claude Code
版本: 2.0.0
"""

import sys
import json
import logging
import argparse
import time
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime

# 添加src/test到路径
sys.path.insert(0, str(Path(__file__).parent / "src" / "test"))

from invariant_toolkit import InvariantGeneratorV2

# ============================================================================
# 配置
# ============================================================================

LOG_FORMAT = '%(asctime)s - [%(levelname)s] - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# 获取脚本所在目录
SCRIPT_DIR = Path(__file__).parent
EXTRACTED_CONTRACTS_DIR = SCRIPT_DIR / "extracted_contracts"

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ProjectInfo:
    """项目信息"""
    name: str
    path: Path
    has_before_after: bool
    already_generated: bool

@dataclass
class GenerationResult:
    """生成结果"""
    project_name: str
    success: bool
    skipped: bool
    invariant_count: int = 0
    protocol_type: Optional[str] = None
    error_message: Optional[str] = None
    duration: float = 0.0

# ============================================================================
# 项目扫描器
# ============================================================================

class ProjectScanner:
    """扫描并收集符合条件的项目"""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.logger = logging.getLogger(self.__class__.__name__)

    def scan_projects(
        self,
        filter_pattern: Optional[str] = None,
        force: bool = False
    ) -> List[ProjectInfo]:
        """
        扫描所有符合条件的项目

        Args:
            filter_pattern: 过滤模式(如 "2024-01")
            force: 是否强制重新生成

        Returns:
            项目信息列表
        """
        projects = []

        # 扫描目录
        if filter_pattern:
            pattern_dirs = list(self.base_dir.glob(filter_pattern))
        else:
            pattern_dirs = [self.base_dir]

        for pattern_dir in pattern_dirs:
            if not pattern_dir.is_dir():
                continue

            # 遍历该目录下的所有项目
            for project_dir in sorted(pattern_dir.iterdir()):
                if not project_dir.is_dir():
                    continue

                # 检查是否有before/after数据
                before_file = project_dir / "attack_state.json"
                after_file = project_dir / "attack_state_after.json"

                has_before_after = before_file.exists() and after_file.exists()

                # 检查是否已生成
                output_file = project_dir / "invariants_v2.json"
                already_generated = output_file.exists() and not force

                projects.append(ProjectInfo(
                    name=project_dir.name,
                    path=project_dir,
                    has_before_after=has_before_after,
                    already_generated=already_generated
                ))

        self.logger.info(f"扫描完成: 找到 {len(projects)} 个项目")

        # 统计
        with_data = sum(1 for p in projects if p.has_before_after)
        already_done = sum(1 for p in projects if p.already_generated)

        self.logger.info(f"  - 有before/after数据: {with_data}")
        self.logger.info(f"  - 已生成: {already_done}")
        self.logger.info(f"  - 待处理: {with_data - already_done}")

        return projects

# ============================================================================
# 批量生成器
# ============================================================================

class BatchGenerator:
    """批量生成不变量"""

    def __init__(self):
        self.generator = InvariantGeneratorV2()
        self.logger = logging.getLogger(self.__class__.__name__)

    def process_single_project(self, project: ProjectInfo) -> GenerationResult:
        """
        处理单个项目

        Args:
            project: 项目信息

        Returns:
            生成结果
        """
        start_time = time.time()

        # 跳过检查
        if project.already_generated:
            return GenerationResult(
                project_name=project.name,
                success=True,
                skipped=True
            )

        if not project.has_before_after:
            return GenerationResult(
                project_name=project.name,
                success=False,
                skipped=True,
                error_message="缺少before/after数据"
            )

        try:
            # 生成不变量
            result = self.generator.generate_from_project(project.path)

            duration = time.time() - start_time

            return GenerationResult(
                project_name=project.name,
                success=True,
                skipped=False,
                invariant_count=result["statistics"]["total_invariants"],
                protocol_type=result.get("protocol_type"),
                duration=duration
            )

        except Exception as e:
            self.logger.error(f"处理 {project.name} 失败: {e}", exc_info=True)

            duration = time.time() - start_time

            return GenerationResult(
                project_name=project.name,
                success=False,
                skipped=False,
                error_message=str(e),
                duration=duration
            )

    def batch_process(
        self,
        projects: List[ProjectInfo],
        max_workers: int = 4
    ) -> List[GenerationResult]:
        """
        并行处理多个项目

        Args:
            projects: 项目列表
            max_workers: 最大并行数

        Returns:
            生成结果列表
        """
        results = []

        # 过滤需要处理的项目
        to_process = [p for p in projects if not p.already_generated and p.has_before_after]

        if not to_process:
            self.logger.info("没有需要处理的项目")
            return results

        self.logger.info(f"开始批量处理: {len(to_process)} 个项目, {max_workers} 个worker")

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交任务
            future_to_project = {
                executor.submit(self.process_single_project, project): project
                for project in to_process
            }

            # 收集结果
            for i, future in enumerate(as_completed(future_to_project), 1):
                project = future_to_project[future]

                try:
                    result = future.result()
                    results.append(result)

                    if result.success and not result.skipped:
                        self.logger.info(
                            f"[{i}/{len(to_process)}] ✅ {project.name}: "
                            f"{result.invariant_count} 个不变量 "
                            f"({result.protocol_type}) "
                            f"耗时 {result.duration:.1f}s"
                        )
                    elif result.skipped:
                        self.logger.info(f"[{i}/{len(to_process)}] ⏭️  {project.name}: 跳过")
                    else:
                        self.logger.error(
                            f"[{i}/{len(to_process)}] ❌ {project.name}: "
                            f"{result.error_message}"
                        )

                except Exception as e:
                    self.logger.error(f"[{i}/{len(to_process)}] ❌ {project.name}: {e}")
                    results.append(GenerationResult(
                        project_name=project.name,
                        success=False,
                        skipped=False,
                        error_message=str(e)
                    ))

        return results

# ============================================================================
# 报告生成器
# ============================================================================

class ReportGenerator:
    """生成批处理报告"""

    @staticmethod
    def generate_report(results: List[GenerationResult]) -> Dict:
        """生成统计报告"""
        total = len(results)
        successful = sum(1 for r in results if r.success and not r.skipped)
        skipped = sum(1 for r in results if r.skipped)
        failed = sum(1 for r in results if not r.success and not r.skipped)

        total_invariants = sum(r.invariant_count for r in results if r.success)
        avg_invariants = total_invariants / successful if successful > 0 else 0

        total_time = sum(r.duration for r in results)

        # 按协议类型统计
        by_protocol = {}
        for r in results:
            if r.success and r.protocol_type:
                by_protocol[r.protocol_type] = by_protocol.get(r.protocol_type, 0) + 1

        return {
            "total_projects": total,
            "successful": successful,
            "skipped": skipped,
            "failed": failed,
            "total_invariants": total_invariants,
            "avg_invariants_per_project": round(avg_invariants, 1),
            "total_time_seconds": round(total_time, 1),
            "by_protocol_type": by_protocol,
            "failed_projects": [
                {"name": r.project_name, "error": r.error_message}
                for r in results if not r.success and not r.skipped
            ]
        }

    @staticmethod
    def print_report(report: Dict):
        """打印报告"""
        print("\n" + "="*80)
        print(" 批量生成报告 - v2.0")
        print("="*80)
        print(f"\n总项目数: {report['total_projects']}")
        print(f"  ✅ 成功: {report['successful']}")
        print(f"  ⏭️  跳过: {report['skipped']}")
        print(f"  ❌ 失败: {report['failed']}")

        print(f"\n不变量统计:")
        print(f"  总数: {report['total_invariants']}")
        print(f"  平均: {report['avg_invariants_per_project']} 个/项目")

        print(f"\n耗时: {report['total_time_seconds']} 秒")

        if report['by_protocol_type']:
            print(f"\n协议类型分布:")
            for ptype, count in sorted(report['by_protocol_type'].items(), key=lambda x: -x[1]):
                print(f"  {ptype}: {count} 个项目")

        if report['failed_projects']:
            print(f"\n失败的项目:")
            for failed in report['failed_projects']:
                print(f"  - {failed['name']}: {failed['error']}")

        print("\n" + "="*80)

# ============================================================================
# 主函数
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="批量生成不变量 - v2.0版本"
    )
    parser.add_argument(
        "--filter",
        default="2024-*",
        help="过滤模式 (如: 2024-01, 2024-*, *)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="并行worker数量 (默认: 4)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新生成(即使已存在)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式,不实际生成"
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=EXTRACTED_CONTRACTS_DIR,
        help=f"基础目录 (默认: {EXTRACTED_CONTRACTS_DIR})"
    )

    args = parser.parse_args()

    # 扫描项目
    scanner = ProjectScanner(args.base_dir)
    projects = scanner.scan_projects(
        filter_pattern=args.filter,
        force=args.force
    )

    if args.dry_run:
        print("\n🔍 预览模式 - 不会实际生成\n")
        for p in projects:
            status = "✅" if p.has_before_after else "⚠️"
            already = "(已生成)" if p.already_generated else ""
            print(f"{status} {p.name} {already}")
        return

    # 批量生成
    generator = BatchGenerator()
    results = generator.batch_process(projects, max_workers=args.workers)

    # 生成报告
    report = ReportGenerator.generate_report(results)
    ReportGenerator.print_report(report)

    # 保存报告
    report_file = args.base_dir / f"batch_generation_report_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    logger.info(f"报告已保存: {report_file}")

if __name__ == "__main__":
    main()
