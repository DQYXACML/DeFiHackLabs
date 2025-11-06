#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
运行时指标提取器

功能：从Go Monitor的JSON输出提取运行时指标
支持的指标：
- gas_used: Gas消耗
- call_depth: 调用深度
- reentrancy_depth: 重入深度
- loop_iterations: 循环迭代次数
- pool_utilization: 池子利用率
- balance_changes: 余额变化
- function_calls: 函数调用统计
- call_sequence: 调用序列
"""

import json
import logging
import subprocess
from typing import Dict, List, Optional
from pathlib import Path
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class RuntimeMetrics:
    """运行时指标数据类"""
    gas_used: int = 0
    call_depth: int = 0
    reentrancy_depth: int = 0
    loop_iterations: int = 0
    pool_utilization: float = 0.0
    balance_changes: Dict[str, Dict] = None
    function_calls: Dict[str, int] = None
    call_sequence: List[str] = None

    def __post_init__(self):
        if self.balance_changes is None:
            self.balance_changes = {}
        if self.function_calls is None:
            self.function_calls = {}
        if self.call_sequence is None:
            self.call_sequence = []

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'gas_used': self.gas_used,
            'call_depth': self.call_depth,
            'reentrancy_depth': self.reentrancy_depth,
            'loop_iterations': self.loop_iterations,
            'pool_utilization': self.pool_utilization,
            'balance_changes': self.balance_changes,
            'function_calls': self.function_calls,
            'call_sequence': self.call_sequence
        }


class RuntimeMetricsExtractor:
    """运行时指标提取器"""

    def __init__(self, monitor_path: str = "./autopath/monitor"):
        """
        初始化提取器

        Args:
            monitor_path: Go Monitor可执行文件路径
        """
        self.monitor_path = Path(monitor_path)

    def extract_from_monitor_output(self, monitor_output_file: Path) -> RuntimeMetrics:
        """
        从Monitor输出JSON文件中提取指标

        Args:
            monitor_output_file: Monitor输出的JSON文件路径

        Returns:
            RuntimeMetrics对象
        """
        if not monitor_output_file.exists():
            logger.error(f"Monitor输出文件不存在: {monitor_output_file}")
            return RuntimeMetrics()

        try:
            with open(monitor_output_file, 'r') as f:
                data = json.load(f)

            return self._parse_monitor_json(data)

        except Exception as e:
            logger.error(f"解析Monitor输出失败: {e}")
            return RuntimeMetrics()

    def run_monitor_and_extract(
        self,
        tx_hash: str,
        rpc_url: str,
        config_file: Optional[Path] = None,
        output_file: Optional[Path] = None
    ) -> RuntimeMetrics:
        """
        运行Go Monitor并提取指标

        Args:
            tx_hash: 交易哈希
            rpc_url: RPC URL
            config_file: 不变量配置文件（可选）
            output_file: 输出文件路径（可选）

        Returns:
            RuntimeMetrics对象
        """
        # 检查Monitor是否存在
        if not self.monitor_path.exists():
            logger.error(f"Monitor可执行文件不存在: {self.monitor_path}")
            logger.info("尝试编译Monitor...")
            self._compile_monitor()

        # 准备输出文件
        if output_file is None:
            output_file = Path(f"/tmp/monitor_{tx_hash[:8]}.json")

        # 构建命令
        cmd = [
            str(self.monitor_path),
            '--tx', tx_hash,
            '--rpc', rpc_url,
            '--output', str(output_file)
        ]

        if config_file and config_file.exists():
            cmd.extend(['--config', str(config_file)])

        # 运行Monitor
        logger.info(f"运行Monitor: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.error(f"Monitor执行失败: {result.stderr}")
                return RuntimeMetrics()

            logger.info("Monitor执行成功")

            # 提取指标
            return self.extract_from_monitor_output(output_file)

        except subprocess.TimeoutExpired:
            logger.error("Monitor执行超时")
            return RuntimeMetrics()
        except Exception as e:
            logger.error(f"运行Monitor异常: {e}")
            return RuntimeMetrics()

    def extract_from_trace(
        self,
        tx_hash: str,
        rpc_url: str
    ) -> RuntimeMetrics:
        """
        直接从交易trace中提取基本指标（不依赖Monitor）

        Args:
            tx_hash: 交易哈希
            rpc_url: RPC URL

        Returns:
            RuntimeMetrics对象
        """
        metrics = RuntimeMetrics()

        try:
            # 获取交易receipt
            receipt = self._get_transaction_receipt(tx_hash, rpc_url)
            if receipt:
                metrics.gas_used = int(receipt.get('gasUsed', '0x0'), 16)

            # 获取trace
            trace = self._get_transaction_trace(tx_hash, rpc_url)
            if trace:
                # 分析trace
                metrics.call_depth = self._calculate_call_depth(trace)
                metrics.reentrancy_depth = self._calculate_reentrancy_depth(trace)
                metrics.function_calls = self._extract_function_calls(trace)
                metrics.call_sequence = self._extract_call_sequence(trace)
                metrics.loop_iterations = self._estimate_loop_iterations(trace)

        except Exception as e:
            logger.error(f"从trace提取指标失败: {e}")

        return metrics

    # ==================== 内部方法 ====================

    def _parse_monitor_json(self, data: Dict) -> RuntimeMetrics:
        """解析Monitor的JSON输出"""
        metrics = RuntimeMetrics()

        # 提取transaction_data字段
        tx_data = data.get('transaction_data', {})

        metrics.gas_used = tx_data.get('gas_used', 0)
        metrics.call_depth = tx_data.get('call_depth', 0)
        metrics.reentrancy_depth = tx_data.get('reentrancy_depth', 0)
        metrics.loop_iterations = tx_data.get('loop_iterations', 0)
        metrics.pool_utilization = tx_data.get('pool_utilization', 0.0)

        # 余额变化
        balance_changes = tx_data.get('balance_changes', {})
        for addr, change_data in balance_changes.items():
            metrics.balance_changes[addr.lower()] = {
                'before': int(change_data.get('before', '0')),
                'after': int(change_data.get('after', '0')),
                'difference': int(change_data.get('difference', '0')),
                'change_rate': float(change_data.get('change_rate', 0.0))
            }

        # 函数调用统计
        metrics.function_calls = tx_data.get('function_calls', {})

        # 调用序列
        metrics.call_sequence = tx_data.get('call_sequence', [])

        return metrics

    def _get_transaction_receipt(self, tx_hash: str, rpc_url: str) -> Optional[Dict]:
        """获取交易receipt"""
        try:
            result = subprocess.run(
                ['cast', 'receipt', tx_hash, '--rpc-url', rpc_url, '--json'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return json.loads(result.stdout)

        except Exception as e:
            logger.error(f"获取交易receipt失败: {e}")

        return None

    def _get_transaction_trace(self, tx_hash: str, rpc_url: str) -> Optional[Dict]:
        """获取交易trace (使用cast)"""
        try:
            result = subprocess.run(
                ['cast', 'run', tx_hash, '--rpc-url', rpc_url, '--json'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return json.loads(result.stdout)

        except Exception as e:
            logger.error(f"获取交易trace失败: {e}")

        return None

    def _calculate_call_depth(self, trace: Dict) -> int:
        """计算调用深度"""
        def get_depth(node, current_depth=1):
            if 'calls' not in node or not node['calls']:
                return current_depth

            max_child_depth = current_depth
            for call in node['calls']:
                child_depth = get_depth(call, current_depth + 1)
                max_child_depth = max(max_child_depth, child_depth)

            return max_child_depth

        return get_depth(trace)

    def _calculate_reentrancy_depth(self, trace: Dict) -> int:
        """计算重入深度"""
        def find_reentrancy(node, visited, current_depth=0):
            to_addr = node.get('to', '').lower()

            if to_addr in visited:
                # 发现重入
                return visited[to_addr] + 1

            visited[to_addr] = current_depth
            max_reentrancy = 0

            if 'calls' in node:
                for call in node['calls']:
                    visited_copy = visited.copy()
                    reentrancy = find_reentrancy(call, visited_copy, current_depth + 1)
                    max_reentrancy = max(max_reentrancy, reentrancy)

            return max_reentrancy

        return find_reentrancy(trace, {})

    def _extract_function_calls(self, trace: Dict) -> Dict[str, int]:
        """提取函数调用统计"""
        call_counts = {}

        def count_calls(node):
            # 提取函数选择器（input的前10个字符：0x + 8位十六进制）
            input_data = node.get('input', '')
            if len(input_data) >= 10:
                func_sig = input_data[:10]
                call_counts[func_sig] = call_counts.get(func_sig, 0) + 1

            # 递归处理子调用
            if 'calls' in node:
                for call in node['calls']:
                    count_calls(call)

        count_calls(trace)
        return call_counts

    def _extract_call_sequence(self, trace: Dict) -> List[str]:
        """提取调用序列"""
        sequence = []

        def traverse(node):
            input_data = node.get('input', '')
            if len(input_data) >= 10:
                func_sig = input_data[:10]
                sequence.append(func_sig)

            if 'calls' in node:
                for call in node['calls']:
                    traverse(call)

        traverse(trace)
        return sequence

    def _estimate_loop_iterations(self, trace: Dict) -> int:
        """估算循环迭代次数（通过相同函数调用次数）"""
        function_calls = self._extract_function_calls(trace)

        # 找到调用次数最多的函数
        if not function_calls:
            return 0

        max_count = max(function_calls.values())

        # 如果某个函数调用次数 >= 3，认为是循环
        return max_count if max_count >= 3 else 0

    def _compile_monitor(self):
        """编译Go Monitor"""
        autopath_dir = self.monitor_path.parent

        if not autopath_dir.exists():
            logger.error(f"autopath目录不存在: {autopath_dir}")
            return

        try:
            logger.info("开始编译Monitor...")

            # go mod tidy
            subprocess.run(
                ['go', 'mod', 'tidy'],
                cwd=autopath_dir,
                check=True,
                timeout=60
            )

            # go build
            subprocess.run(
                ['go', 'build', '-o', 'monitor', './cmd/monitor'],
                cwd=autopath_dir,
                check=True,
                timeout=120
            )

            logger.info("Monitor编译成功")

        except Exception as e:
            logger.error(f"编译Monitor失败: {e}")


if __name__ == '__main__':
    # 测试示例
    extractor = RuntimeMetricsExtractor()

    # 测试解析Monitor输出
    test_monitor_output = {
        "event_name": "BarleyFinance_exp",
        "transaction_data": {
            "tx_hash": "0x...",
            "gas_used": 2345678,
            "call_depth": 5,
            "reentrancy_depth": 0,
            "loop_iterations": 20,
            "pool_utilization": 99.8,
            "balance_changes": {
                "0xAttacker": {
                    "before": "1000000000000000000",
                    "after": "5000000000000000000",
                    "difference": "4000000000000000000",
                    "change_rate": 4.0
                }
            },
            "function_calls": {
                "0x3b30ba59": 20,
                "0x095ea7b3": 15
            },
            "call_sequence": ["0x3b30ba59", "0x095ea7b3"]
        }
    }

    metrics = extractor._parse_monitor_json(test_monitor_output)
    print(f"\n{'='*60}")
    print(f"运行时指标:")
    print(f"- Gas使用: {metrics.gas_used}")
    print(f"- 调用深度: {metrics.call_depth}")
    print(f"- 重入深度: {metrics.reentrancy_depth}")
    print(f"- 循环迭代: {metrics.loop_iterations}")
    print(f"- 池子利用率: {metrics.pool_utilization}%")
    print(f"- 余额变化: {len(metrics.balance_changes)}个地址")
    print(f"- 函数调用: {metrics.function_calls}")
