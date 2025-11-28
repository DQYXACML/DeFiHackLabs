#!/usr/bin/env python3
"""
DeFi攻击合约源码提取工具 - 并行版本

相比原版的性能优化:
1. 并行处理多个测试脚本(可配置并发数)
2. 动态分析可选(默认关闭,因为forge test很慢)
3. 优化的API调用策略

作者: Claude Code
版本: 2.0.0 (Parallel)
"""

import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import logging
from typing import Optional, List
import multiprocessing as mp

# 导入原始脚本的所有功能
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 从原始脚本导入
from extract_contracts import (
    ContractExtractor,
    ExploitScript,
    DEFAULT_API_KEYS,
    DEFAULT_TEST_DIR,
    DEFAULT_OUTPUT_DIR,
    LOG_FORMAT,
    logger
)

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


def process_single_script(script: ExploitScript, output_dir: Path,
                         api_keys: dict, static_only: bool = True) -> dict:
    """
    处理单个脚本 (在独立进程中执行)

    Args:
        script: 攻击脚本对象
        output_dir: 输出目录
        api_keys: API密钥配置
        static_only: 是否只做静态分析

    Returns:
        处理结果字典
    """
    # 在子进程中重新初始化logger
    logger = logging.getLogger(__name__)

    try:
        # 创建临时提取器(每个进程独立)
        extractor = ContractExtractor(
            test_dir=script.file_path.parent.parent,
            output_dir=output_dir,
            api_keys=api_keys
        )

        # 如果只做静态分析,禁用动态分析器
        if static_only:
            extractor.dynamic_analyzer = None

        # 处理脚本
        unverified_contracts = []
        success = extractor._process_script(script, unverified_contracts)

        return {
            'script': script.name,
            'date_dir': script.date_dir,
            'success': success,
            'addresses': extractor.summary.total_addresses,
            'verified': extractor.summary.verified_contracts,
            'unverified': extractor.summary.unverified_contracts,
            'bytecode_only': extractor.summary.bytecode_only_contracts,
            'errors': extractor.summary.errors
        }

    except Exception as e:
        logger.error(f"处理脚本 {script.name} 失败: {e}")
        return {
            'script': script.name,
            'date_dir': script.date_dir,
            'success': False,
            'error': str(e)
        }


class ParallelContractExtractor:
    """并行合约提取器"""

    def __init__(self, test_dir: Path, output_dir: Path,
                 api_keys: Optional[dict] = None,
                 max_workers: Optional[int] = None,
                 static_only: bool = True):
        """
        初始化并行提取器

        Args:
            test_dir: 测试脚本目录
            output_dir: 输出目录
            api_keys: API密钥配置
            max_workers: 最大并发进程数(默认为CPU核心数)
            static_only: 是否只做静态分析(默认True,因为forge test很慢)
        """
        self.test_dir = test_dir
        self.output_dir = output_dir
        self.api_keys = api_keys or DEFAULT_API_KEYS
        self.max_workers = max_workers or max(1, mp.cpu_count() - 1)
        self.static_only = static_only
        self.logger = logging.getLogger(__name__)

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"并行提取器初始化: {self.max_workers} 个工作进程")
        if self.static_only:
            self.logger.info("模式: 静态分析only (跳过forge test)")
        else:
            self.logger.info("模式: 静态+动态分析 (包含forge test,会较慢)")

    def extract_all(self, date_filters: Optional[List[str]] = None):
        """
        并行提取所有脚本的合约

        Args:
            date_filters: 日期过滤器列表
        """
        self.logger.info("=" * 80)
        self.logger.info("开始并行提取DeFi攻击合约")
        self.logger.info("=" * 80)

        # 查找所有测试脚本
        scripts = self._find_all_scripts(date_filters)
        total_scripts = len(scripts)

        if total_scripts == 0:
            self.logger.warning("未找到任何测试脚本")
            return

        self.logger.info(f"找到 {total_scripts} 个测试脚本")
        self.logger.info(f"开始并行处理 (并发数: {self.max_workers})...")

        # 统计信息
        results = {
            'total': total_scripts,
            'successful': 0,
            'failed': 0,
            'total_addresses': 0,
            'verified_contracts': 0,
            'unverified_contracts': 0,
            'bytecode_only_contracts': 0,
            'errors': []
        }

        # 使用进程池并行处理
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任务
            futures = {
                executor.submit(
                    process_single_script,
                    script,
                    self.output_dir,
                    self.api_keys,
                    self.static_only
                ): script
                for script in scripts
            }

            # 等待完成并收集结果
            completed = 0
            for future in as_completed(futures):
                completed += 1
                script = futures[future]

                try:
                    result = future.result()

                    # 更新统计
                    if result.get('success'):
                        results['successful'] += 1
                        results['total_addresses'] += result.get('addresses', 0)
                        results['verified_contracts'] += result.get('verified', 0)
                        results['unverified_contracts'] += result.get('unverified', 0)
                        results['bytecode_only_contracts'] += result.get('bytecode_only', 0)
                    else:
                        results['failed'] += 1

                    if result.get('errors'):
                        results['errors'].extend(result['errors'])

                    # 显示进度
                    status = "✓" if result.get('success') else "✗"
                    self.logger.info(
                        f"[{completed}/{total_scripts}] {status} "
                        f"{result['date_dir']}/{result['script']} - "
                        f"{result.get('addresses', 0)} 个地址"
                    )

                except Exception as e:
                    self.logger.error(f"处理 {script.name} 时发生异常: {e}")
                    results['failed'] += 1

        # 打印统计
        self._print_summary(results)

    def _find_all_scripts(self, date_filters: Optional[List[str]] = None) -> List[ExploitScript]:
        """查找所有测试脚本 (复用原始逻辑)"""
        import re
        scripts = []

        for date_dir in sorted(self.test_dir.iterdir()):
            if not date_dir.is_dir():
                continue

            if not re.match(r'\d{4}-\d{2}', date_dir.name):
                continue

            if date_filters and not any(date_dir.name.startswith(f) for f in date_filters):
                continue

            for sol_file in date_dir.glob('*.sol'):
                script = ExploitScript(
                    file_path=sol_file,
                    name=sol_file.stem,
                    date_dir=date_dir.name
                )
                scripts.append(script)

        return scripts

    def _print_summary(self, results: dict):
        """打印执行摘要"""
        self.logger.info("\n" + "=" * 80)
        self.logger.info("执行摘要")
        self.logger.info("=" * 80)
        self.logger.info(f"总脚本数:        {results['total']}")
        self.logger.info(f"成功:            {results['successful']}")
        self.logger.info(f"失败:            {results['failed']}")
        self.logger.info(f"总地址数:        {results['total_addresses']}")
        self.logger.info(f"已验证合约:      {results['verified_contracts']}")
        self.logger.info(f"未验证合约:      {results['unverified_contracts']}")
        self.logger.info(f"  └─ 仅字节码:   {results['bytecode_only_contracts']}")
        self.logger.info(f"\n输出目录:        {self.output_dir}")
        if results['errors']:
            self.logger.info(f"错误数:          {len(results['errors'])}")
        self.logger.info("=" * 80)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='DeFi攻击合约源码提取工具 - 并行版本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 快速模式: 只做静态分析,并行处理
  python extract_contracts_parallel.py --filter 2024-01

  # 完整模式: 包含forge test (慢,但更完整)
  python extract_contracts_parallel.py --filter 2024-01 --no-static-only

  # 自定义并发数
  python extract_contracts_parallel.py --filter 2024-01 --workers 4

  # 处理所有脚本
  python extract_contracts_parallel.py
        """
    )

    parser.add_argument(
        '--test-dir',
        type=Path,
        default=DEFAULT_TEST_DIR,
        help='测试脚本目录'
    )

    parser.add_argument(
        '--output-dir',
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help='输出目录'
    )

    parser.add_argument(
        '--filter',
        dest='filters',
        action='append',
        help='日期过滤器 (如: 2024-01)'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=None,
        help=f'并发进程数 (默认: CPU核心数-1, 当前系统: {mp.cpu_count()}核)'
    )

    parser.add_argument(
        '--no-static-only',
        action='store_true',
        help='启用动态分析(forge test) - 会显著变慢'
    )

    parser.add_argument(
        '--api-key',
        type=str,
        help='覆盖默认的Etherscan API Key'
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

    # API Keys
    api_keys = DEFAULT_API_KEYS.copy()
    if args.api_key:
        api_keys['etherscan'] = args.api_key
        logger.info("使用自定义Etherscan API Key")

    # 创建并行提取器
    extractor = ParallelContractExtractor(
        test_dir=args.test_dir,
        output_dir=args.output_dir,
        api_keys=api_keys,
        max_workers=args.workers,
        static_only=not args.no_static_only
    )

    # 解析日期过滤器
    date_filters = None
    if args.filters:
        parsed_filters = []
        for value in args.filters:
            for item in value.split(','):
                item = item.strip()
                if item:
                    parsed_filters.append(item)
        if parsed_filters:
            date_filters = sorted(set(parsed_filters))

    # 执行提取
    try:
        extractor.extract_all(date_filters=date_filters)
    except KeyboardInterrupt:
        logger.info("\n\n用户中断")


if __name__ == '__main__':
    main()
