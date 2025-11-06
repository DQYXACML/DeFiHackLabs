#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
报告生成器

功能：
- 生成Markdown格式的人类可读报告
- 生成JSON格式的机器可读报告
- 生成CSV格式的汇总统计
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import csv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ReportBuilder:
    """报告构建器"""

    def __init__(
        self,
        event_name: str,
        year_month: str,
        output_dir: Path
    ):
        """
        初始化报告构建器

        Args:
            event_name: 攻击事件名称
            year_month: 年月目录
            output_dir: 输出目录
        """
        self.event_name = event_name
        self.year_month = year_month
        self.output_dir = output_dir

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_report(
        self,
        invariants: List[Dict],
        violation_results: List,
        storage_changes: Dict,
        runtime_metrics: Optional[Dict],
        attack_tx_hash: Optional[str] = None
    ):
        """
        生成完整报告

        Args:
            invariants: 不变量列表
            violation_results: 违规结果列表
            storage_changes: 存储变化
            runtime_metrics: 运行时指标
            attack_tx_hash: 攻击交易hash
        """
        # 生成Markdown报告
        markdown_file = self.output_dir / f"{self.event_name}_dynamic_report.md"
        self._generate_markdown(
            markdown_file,
            invariants,
            violation_results,
            storage_changes,
            runtime_metrics,
            attack_tx_hash
        )

        # 生成JSON报告
        json_file = self.output_dir / f"{self.event_name}_dynamic_report.json"
        self._generate_json(
            json_file,
            invariants,
            violation_results,
            storage_changes,
            runtime_metrics,
            attack_tx_hash
        )

        logger.info(f"报告已生成:")
        logger.info(f"  - Markdown: {markdown_file}")
        logger.info(f"  - JSON: {json_file}")

    def _generate_markdown(
        self,
        output_file: Path,
        invariants: List[Dict],
        violation_results: List,
        storage_changes: Dict,
        runtime_metrics: Optional[Dict],
        attack_tx_hash: Optional[str]
    ):
        """生成Markdown报告"""
        violations = [r for r in violation_results if r.violated]
        passed = [r for r in violation_results if not r.violated]

        md_lines = []

        # 标题
        md_lines.append(f"# 动态不变量检测报告 - {self.event_name}\n")
        md_lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        md_lines.append("---\n")

        # 基本信息
        md_lines.append("## 📋 基本信息\n")
        md_lines.append(f"- **攻击名称**: {self.event_name}")
        md_lines.append(f"- **年月**: {self.year_month}")
        if attack_tx_hash:
            md_lines.append(f"- **攻击交易**: `{attack_tx_hash}`")
        md_lines.append(f"- **检测方法**: 动态执行（Anvil重放）\n")

        # 执行摘要
        md_lines.append("## 📊 执行摘要\n")
        md_lines.append(f"- **总不变量数**: {len(violation_results)}")
        md_lines.append(f"- **违规数量**: {len(violations)} ❌")
        md_lines.append(f"- **通过数量**: {len(passed)} ✅")
        md_lines.append(f"- **违规率**: {len(violations) / len(violation_results) * 100:.1f}%\n" if violation_results else "- **违规率**: N/A\n")

        # 运行时指标
        if runtime_metrics:
            md_lines.append("## ⚡ 运行时指标\n")
            md_lines.append(f"- **Gas使用**: {runtime_metrics.get('gas_used', 'N/A'):,}")
            md_lines.append(f"- **调用深度**: {runtime_metrics.get('call_depth', 'N/A')}")
            md_lines.append(f"- **重入深度**: {runtime_metrics.get('reentrancy_depth', 'N/A')}")
            md_lines.append(f"- **循环迭代**: {runtime_metrics.get('loop_iterations', 'N/A')}")
            md_lines.append(f"- **池子利用率**: {runtime_metrics.get('pool_utilization', 'N/A')}%\n")

        # 违规详情
        if violations:
            md_lines.append("## ❌ 违规详情\n")

            for i, v in enumerate(violations, 1):
                md_lines.append(f"### {i}. [{v.invariant_id}] {v.invariant_type}\n")
                md_lines.append(f"**严重程度**: `{v.severity.value.upper()}`\n")
                md_lines.append(f"**描述**: {v.description}\n")
                md_lines.append(f"**阈值**: `{v.threshold}`")
                md_lines.append(f"**实际值**: `{v.actual_value}` 🚨\n")
                md_lines.append(f"**影响**: {v.impact}\n")

                # 证据
                md_lines.append("**证据**:")
                md_lines.append("```json")
                md_lines.append(json.dumps(v.evidence, indent=2))
                md_lines.append("```\n")
                md_lines.append("---\n")

        # 通过的不变量
        if passed:
            md_lines.append("## ✅ 通过检测的不变量\n")

            for i, v in enumerate(passed, 1):
                md_lines.append(f"{i}. **[{v.invariant_id}]** {v.invariant_type} - {v.description}")
                md_lines.append(f"   - 阈值: `{v.threshold}`, 实际: `{v.actual_value}`\n")

        # 存储变化摘要
        md_lines.append("## 📦 存储变化摘要\n")

        if storage_changes:
            # 统计有变化的存储槽数量
            total_slots = sum(len(slots) for contract, slots in storage_changes.items()
                              if contract != 'balances')

            md_lines.append(f"- **变化的合约数**: {len([c for c in storage_changes.keys() if c != 'balances'])}")
            md_lines.append(f"- **变化的存储槽数**: {total_slots}")

            # 显示最大变化
            max_changes = []
            for contract, slots in storage_changes.items():
                if contract == 'balances':
                    continue
                for slot, data in slots.items():
                    change_rate = data.get('change_rate', 0)
                    if change_rate > 0:
                        max_changes.append((contract, slot, change_rate, data))

            # 排序并显示前5
            max_changes.sort(key=lambda x: x[2], reverse=True)

            if max_changes:
                md_lines.append("\n**变化率最大的存储槽**:\n")
                for contract, slot, rate, data in max_changes[:5]:
                    md_lines.append(f"- `{contract[:10]}...` slot {slot}: "
                                    f"{data['before']} → {data['after']} "
                                    f"(变化 {data['change_pct']})")

        md_lines.append("\n---")
        md_lines.append(f"\n*报告由动态不变量检测器自动生成*")

        # 写入文件
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md_lines))

    def _generate_json(
        self,
        output_file: Path,
        invariants: List[Dict],
        violation_results: List,
        storage_changes: Dict,
        runtime_metrics: Optional[Dict],
        attack_tx_hash: Optional[str]
    ):
        """生成JSON报告"""
        violations = [r for r in violation_results if r.violated]

        report = {
            'report_metadata': {
                'event_name': self.event_name,
                'year_month': self.year_month,
                'generated_at': datetime.now().isoformat(),
                'detection_method': 'dynamic_execution',
                'attack_tx_hash': attack_tx_hash
            },
            'summary': {
                'total_invariants': len(violation_results),
                'violations_detected': len(violations),
                'passed': len(violation_results) - len(violations),
                'violation_rate': len(violations) / len(violation_results) if violation_results else 0
            },
            'runtime_metrics': runtime_metrics or {},
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
                    'evidence': r.evidence,
                    'confidence': r.confidence
                }
                for r in violation_results
            ],
            'storage_changes_summary': self._summarize_storage_changes(storage_changes)
        }

        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)

    def _summarize_storage_changes(self, storage_changes: Dict) -> Dict:
        """汇总存储变化"""
        summary = {
            'total_contracts_changed': 0,
            'total_slots_changed': 0,
            'max_change_rate': 0,
            'top_changes': []
        }

        all_changes = []

        for contract, slots in storage_changes.items():
            if contract == 'balances':
                continue

            summary['total_contracts_changed'] += 1

            for slot, data in slots.items():
                summary['total_slots_changed'] += 1

                change_rate = data.get('change_rate', 0)
                if change_rate > summary['max_change_rate']:
                    summary['max_change_rate'] = change_rate

                all_changes.append({
                    'contract': contract,
                    'slot': slot,
                    'before': data['before'],
                    'after': data['after'],
                    'change_rate': change_rate,
                    'change_pct': data['change_pct']
                })

        # 按变化率排序，取前10
        all_changes.sort(key=lambda x: x['change_rate'], reverse=True)
        summary['top_changes'] = all_changes[:10]

        return summary

    @staticmethod
    def generate_batch_summary(
        results: List[Dict],
        output_dir: Path
    ):
        """
        生成批量检测的汇总报告

        Args:
            results: 各个攻击的检测结果列表
            output_dir: 输出目录
        """
        # CSV汇总
        csv_file = output_dir / "batch_summary.csv"

        with open(csv_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                '攻击名称',
                '年月',
                '总不变量数',
                '违规数量',
                '通过数量',
                '违规率(%)',
                '状态',
                '检测时间'
            ])

            for result in results:
                writer.writerow([
                    result.get('event_name', ''),
                    result.get('year_month', ''),
                    result.get('total_invariants', 0),
                    result.get('violations', 0),
                    result.get('passed', 0),
                    f"{result.get('violation_rate', 0):.1f}",
                    result.get('status', 'Unknown'),
                    result.get('timestamp', '')
                ])

        # Markdown汇总
        md_file = output_dir / "batch_summary.md"

        md_lines = []
        md_lines.append("# 批量动态检测汇总报告\n")
        md_lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        md_lines.append("---\n")

        # 统计
        total_attacks = len(results)
        successful = len([r for r in results if r.get('status') == 'Success'])
        failed = total_attacks - successful

        md_lines.append("## 📊 总体统计\n")
        md_lines.append(f"- **总攻击数**: {total_attacks}")
        md_lines.append(f"- **成功检测**: {successful} ✅")
        md_lines.append(f"- **检测失败**: {failed} ❌")
        md_lines.append(f"- **成功率**: {successful / total_attacks * 100:.1f}%\n" if total_attacks > 0 else "")

        # 违规统计
        total_violations = sum(r.get('violations', 0) for r in results)
        total_invariants = sum(r.get('total_invariants', 0) for r in results)

        md_lines.append("## 🔍 违规统计\n")
        md_lines.append(f"- **总不变量数**: {total_invariants}")
        md_lines.append(f"- **总违规数**: {total_violations}")
        md_lines.append(f"- **总体违规率**: {total_violations / total_invariants * 100:.1f}%\n" if total_invariants > 0 else "")

        # 详细列表
        md_lines.append("## 📋 详细结果\n")
        md_lines.append("| 攻击名称 | 不变量数 | 违规数 | 违规率 | 状态 |")
        md_lines.append("|---------|---------|--------|-------|------|")

        for result in results:
            name = result.get('event_name', 'Unknown')
            total = result.get('total_invariants', 0)
            violations = result.get('violations', 0)
            rate = result.get('violation_rate', 0)
            status = "✅" if result.get('status') == 'Success' else "❌"

            md_lines.append(f"| {name} | {total} | {violations} | {rate:.1f}% | {status} |")

        md_lines.append("\n---")
        md_lines.append(f"\n*汇总报告由批量动态检测器自动生成*")

        with open(md_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(md_lines))

        logger.info(f"批量汇总报告已生成:")
        logger.info(f"  - CSV: {csv_file}")
        logger.info(f"  - Markdown: {md_file}")


if __name__ == '__main__':
    # 测试示例
    from invariant_evaluator import ViolationResult, ViolationSeverity

    test_results = [
        ViolationResult(
            invariant_id='SINV_001',
            invariant_type='share_price_stability',
            severity=ViolationSeverity.CRITICAL,
            violated=True,
            threshold='5%',
            actual_value='87.3%',
            description='Vault share price must not change more than 5% per transaction',
            impact='Allows attacker to mint underpriced shares',
            evidence={'price_before': 5.0, 'price_after': 2.0}
        )
    ]

    builder = ReportBuilder(
        event_name='TestAttack',
        year_month='2024-01',
        output_dir=Path('/tmp/test_reports')
    )

    builder.build_report(
        invariants=[],
        violation_results=test_results,
        storage_changes={},
        runtime_metrics={'gas_used': 1000000},
        attack_tx_hash='0x123...'
    )
