#!/usr/bin/env python3
"""
生成 InvariantGeneratorV1 vs V2 对比报告

比较以下方面:
1. 不变量数量和类型分布
2. 协议类型检测准确率
3. 攻击模式检测能力
4. 状态变化分析深度
5. 语义映射覆盖率
6. 生成质量评分
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, Counter
import logging

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class InvariantStats:
    """不变量统计数据"""
    total_count: int = 0
    by_category: Dict[str, int] = field(default_factory=dict)
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_type: Dict[str, int] = field(default_factory=dict)


@dataclass
class ProtocolAnalysis:
    """协议分析数据"""
    protocol_name: str
    protocol_type: Optional[str] = None
    protocol_confidence: float = 0.0
    has_v1: bool = False
    has_v2: bool = False

    # v1数据
    v1_invariants: InvariantStats = field(default_factory=InvariantStats)
    v1_patterns: List[str] = field(default_factory=list)

    # v2数据
    v2_invariants: InvariantStats = field(default_factory=InvariantStats)
    v2_attack_patterns: List[Dict] = field(default_factory=list)
    v2_semantic_coverage: float = 0.0
    v2_state_changes: Dict = field(default_factory=dict)

    # 对比指标
    improvement_ratio: float = 0.0
    quality_score: float = 0.0


class ComparisonReportGenerator:
    """对比报告生成器"""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.protocols: List[ProtocolAnalysis] = []

    def scan_protocols(self, year_month: str = "2024-01") -> List[Path]:
        """扫描指定年月的协议目录"""
        search_dir = self.base_dir / year_month

        if not search_dir.exists():
            logger.error(f"目录不存在: {search_dir}")
            return []

        protocol_dirs = [d for d in search_dir.iterdir() if d.is_dir()]
        logger.info(f"找到 {len(protocol_dirs)} 个协议目录")
        return protocol_dirs

    def load_v1_data(self, protocol_dir: Path) -> Optional[Dict]:
        """加载v1不变量数据"""
        v1_path = protocol_dir / "invariants.json"

        if not v1_path.exists():
            return None

        try:
            with open(v1_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"无法加载v1数据 {protocol_dir.name}: {e}")
            return None

    def load_v2_data(self, protocol_dir: Path) -> Optional[Dict]:
        """加载v2不变量数据"""
        v2_path = protocol_dir / "invariants_v2.json"

        if not v2_path.exists():
            return None

        try:
            with open(v2_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"无法加载v2数据 {protocol_dir.name}: {e}")
            return None

    def parse_v1_invariants(self, data: Dict) -> InvariantStats:
        """解析v1不变量统计"""
        stats = InvariantStats()

        # v1版本的不变量在storage_invariants字段
        invariants = data.get("storage_invariants", [])
        stats.total_count = len(invariants)

        # 统计类别和严重程度
        for inv in invariants:
            # 类别 (v1没有category字段，根据type推断)
            inv_type = inv.get("type", "unknown")
            stats.by_type[inv_type] = stats.by_type.get(inv_type, 0) + 1

            # 根据type推断category
            if "balance" in inv_type or "supply" in inv_type:
                category = "balance_constraint"
            elif "price" in inv_type or "ratio" in inv_type:
                category = "ratio_stability"
            elif "reentrancy" in inv_type:
                category = "state_consistency"
            else:
                category = "unknown"
            stats.by_category[category] = stats.by_category.get(category, 0) + 1

            # 严重程度
            severity = inv.get("severity", "unknown")
            stats.by_severity[severity] = stats.by_severity.get(severity, 0) + 1

        return stats

    def parse_v2_invariants(self, data: Dict) -> InvariantStats:
        """解析v2不变量统计"""
        stats = InvariantStats()

        if "statistics" in data:
            stats.total_count = data["statistics"].get("total_invariants", 0)
            stats.by_category = data["statistics"].get("by_category", {})
            stats.by_severity = data["statistics"].get("by_severity", {})

        if "invariants" in data:
            for inv in data["invariants"]:
                inv_type = inv.get("type", "unknown")
                stats.by_type[inv_type] = stats.by_type.get(inv_type, 0) + 1

        return stats

    def calculate_quality_score(self, analysis: ProtocolAnalysis) -> float:
        """计算质量评分 (0-100)"""
        score = 0.0

        # 1. 不变量数量得分 (0-25分)
        if analysis.v2_invariants.total_count > 0:
            # 根据不变量数量给分,最多25分
            count_score = min(analysis.v2_invariants.total_count * 3, 25)
            score += count_score

        # 2. 协议类型检测得分 (0-20分)
        if analysis.protocol_type and analysis.protocol_type != "unknown":
            score += 10 + (analysis.protocol_confidence * 10)

        # 3. 攻击模式检测得分 (0-25分)
        pattern_count = len(analysis.v2_attack_patterns)
        if pattern_count > 0:
            # 根据攻击模式数量和置信度给分
            pattern_score = min(pattern_count * 3, 15)

            # 加上置信度加权
            avg_confidence = sum(p.get("confidence", 0) for p in analysis.v2_attack_patterns) / pattern_count
            confidence_score = avg_confidence * 10

            score += pattern_score + confidence_score

        # 4. 语义映射覆盖率得分 (0-15分)
        if analysis.v2_semantic_coverage > 0:
            score += analysis.v2_semantic_coverage * 100 * 0.15  # 转换为0-15分

        # 5. 状态变化分析深度得分 (0-15分)
        if analysis.v2_state_changes:
            depth_score = 0

            # 合约变化数量
            if analysis.v2_state_changes.get("contracts_changed", 0) > 0:
                depth_score += 5

            # 槽位变化数量
            slots_changed = analysis.v2_state_changes.get("slots_changed", 0)
            if slots_changed > 0:
                depth_score += min(slots_changed / 10, 5)

            # 极端变化检测
            extreme_changes = analysis.v2_state_changes.get("extreme_changes", 0)
            if extreme_changes > 0:
                depth_score += min(extreme_changes / 5, 5)

            score += depth_score

        return min(score, 100.0)  # 最高100分

    def analyze_protocol(self, protocol_dir: Path) -> ProtocolAnalysis:
        """分析单个协议的v1和v2数据"""
        analysis = ProtocolAnalysis(protocol_name=protocol_dir.name)

        # 加载v1数据
        v1_data = self.load_v1_data(protocol_dir)
        if v1_data:
            analysis.has_v1 = True
            analysis.v1_invariants = self.parse_v1_invariants(v1_data)
            analysis.v1_patterns = [inv.get("type", "") for inv in v1_data.get("storage_invariants", [])]

        # 加载v2数据
        v2_data = self.load_v2_data(protocol_dir)
        if v2_data:
            analysis.has_v2 = True
            analysis.protocol_type = v2_data.get("protocol_type")
            analysis.protocol_confidence = v2_data.get("protocol_confidence", 0.0)
            analysis.v2_invariants = self.parse_v2_invariants(v2_data)
            analysis.v2_attack_patterns = v2_data.get("attack_patterns", [])
            analysis.v2_semantic_coverage = v2_data.get("semantic_mapping_coverage", 0.0)
            analysis.v2_state_changes = v2_data.get("state_changes", {})

        # 计算改进比率
        if analysis.has_v1 and analysis.has_v2:
            if analysis.v1_invariants.total_count > 0:
                analysis.improvement_ratio = (
                    (analysis.v2_invariants.total_count - analysis.v1_invariants.total_count)
                    / analysis.v1_invariants.total_count
                )
            else:
                analysis.improvement_ratio = float('inf') if analysis.v2_invariants.total_count > 0 else 0

        # 计算质量评分
        if analysis.has_v2:
            analysis.quality_score = self.calculate_quality_score(analysis)

        return analysis

    def generate_report(self, year_month: str = "2024-01") -> Dict:
        """生成完整对比报告"""
        protocol_dirs = self.scan_protocols(year_month)

        # 分析每个协议
        for protocol_dir in protocol_dirs:
            analysis = self.analyze_protocol(protocol_dir)

            # 只包含有数据的协议
            if analysis.has_v1 or analysis.has_v2:
                self.protocols.append(analysis)

        logger.info(f"分析完成: {len(self.protocols)} 个协议有不变量数据")

        # 生成统计报告
        report = self._generate_statistics()

        return report

    def _generate_statistics(self) -> Dict:
        """生成统计数据"""
        report = {
            "summary": {},
            "protocol_comparison": {},
            "quality_analysis": {},
            "detailed_protocols": []
        }

        # 1. 总体摘要
        total_v1 = sum(1 for p in self.protocols if p.has_v1)
        total_v2 = sum(1 for p in self.protocols if p.has_v2)
        both = sum(1 for p in self.protocols if p.has_v1 and p.has_v2)

        report["summary"] = {
            "total_protocols": len(self.protocols),
            "has_v1_only": total_v1 - both,
            "has_v2_only": total_v2 - both,
            "has_both": both,
            "v1_total_invariants": sum(p.v1_invariants.total_count for p in self.protocols if p.has_v1),
            "v2_total_invariants": sum(p.v2_invariants.total_count for p in self.protocols if p.has_v2)
        }

        # 2. 协议类型分布
        protocol_types_v2 = Counter(p.protocol_type for p in self.protocols if p.has_v2 and p.protocol_type)

        report["protocol_comparison"] = {
            "detected_types": dict(protocol_types_v2),
            "average_confidence": sum(p.protocol_confidence for p in self.protocols if p.has_v2) / max(total_v2, 1)
        }

        # 3. 质量分析
        quality_scores = [p.quality_score for p in self.protocols if p.has_v2]

        if quality_scores:
            report["quality_analysis"] = {
                "average_score": sum(quality_scores) / len(quality_scores),
                "max_score": max(quality_scores),
                "min_score": min(quality_scores),
                "score_distribution": {
                    "excellent (80-100)": len([s for s in quality_scores if s >= 80]),
                    "good (60-80)": len([s for s in quality_scores if 60 <= s < 80]),
                    "fair (40-60)": len([s for s in quality_scores if 40 <= s < 60]),
                    "poor (<40)": len([s for s in quality_scores if s < 40])
                }
            }

        # 4. 详细协议列表
        for protocol in sorted(self.protocols, key=lambda p: p.quality_score, reverse=True):
            protocol_info = {
                "name": protocol.protocol_name,
                "has_v1": protocol.has_v1,
                "has_v2": protocol.has_v2,
                "protocol_type": protocol.protocol_type,
                "quality_score": round(protocol.quality_score, 2)
            }

            if protocol.has_v1:
                protocol_info["v1"] = {
                    "total_invariants": protocol.v1_invariants.total_count,
                    "by_category": protocol.v1_invariants.by_category
                }

            if protocol.has_v2:
                protocol_info["v2"] = {
                    "total_invariants": protocol.v2_invariants.total_count,
                    "by_category": protocol.v2_invariants.by_category,
                    "attack_patterns_count": len(protocol.v2_attack_patterns),
                    "semantic_coverage": round(protocol.v2_semantic_coverage * 100, 2),
                    "state_changes": protocol.v2_state_changes
                }

            if protocol.has_v1 and protocol.has_v2:
                protocol_info["improvement"] = {
                    "absolute": protocol.v2_invariants.total_count - protocol.v1_invariants.total_count,
                    "ratio": round(protocol.improvement_ratio * 100, 2) if protocol.improvement_ratio != float('inf') else "N/A"
                }

            report["detailed_protocols"].append(protocol_info)

        return report

    def print_summary_report(self, report: Dict):
        """打印摘要报告到控制台"""
        print("\n" + "="*80)
        print("InvariantGenerator V1 vs V2 对比报告")
        print("="*80)

        summary = report["summary"]
        print(f"\n【总体统计】")
        print(f"  总协议数: {summary['total_protocols']}")
        print(f"  仅有v1数据: {summary['has_v1_only']}")
        print(f"  仅有v2数据: {summary['has_v2_only']}")
        print(f"  同时有v1和v2: {summary['has_both']}")
        print(f"  v1不变量总数: {summary['v1_total_invariants']}")
        print(f"  v2不变量总数: {summary['v2_total_invariants']}")

        if summary['v1_total_invariants'] > 0:
            improvement = (
                (summary['v2_total_invariants'] - summary['v1_total_invariants'])
                / summary['v1_total_invariants'] * 100
            )
            print(f"  整体改进: {improvement:+.1f}%")

        proto_comp = report["protocol_comparison"]
        print(f"\n【协议类型检测】")
        print(f"  检测到的协议类型:")
        for ptype, count in proto_comp["detected_types"].items():
            print(f"    - {ptype}: {count} 个")
        print(f"  平均置信度: {proto_comp['average_confidence']:.2%}")

        quality = report["quality_analysis"]
        if quality:
            print(f"\n【质量分析】")
            print(f"  平均质量得分: {quality['average_score']:.2f}/100")
            print(f"  最高得分: {quality['max_score']:.2f}")
            print(f"  最低得分: {quality['min_score']:.2f}")
            print(f"  得分分布:")
            for level, count in quality["score_distribution"].items():
                print(f"    - {level}: {count} 个")

        print(f"\n【Top 10 最佳质量协议】")
        top_protocols = report["detailed_protocols"][:10]
        for i, proto in enumerate(top_protocols, 1):
            print(f"  {i}. {proto['name']}")
            print(f"     协议类型: {proto.get('protocol_type', 'N/A')}")
            print(f"     质量得分: {proto['quality_score']:.2f}/100")
            if proto.get('v2'):
                print(f"     v2不变量: {proto['v2']['total_invariants']} 个")
                print(f"     攻击模式: {proto['v2']['attack_patterns_count']} 个")
                print(f"     语义覆盖: {proto['v2']['semantic_coverage']:.2f}%")

        print("\n" + "="*80)

    def save_report(self, report: Dict, output_path: Path):
        """保存报告到JSON文件"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"报告已保存到: {output_path}")


def main():
    """主函数"""
    # 设置路径
    script_dir = Path(__file__).parent
    extracted_dir = script_dir / "extracted_contracts"

    if not extracted_dir.exists():
        logger.error(f"目录不存在: {extracted_dir}")
        sys.exit(1)

    # 生成报告
    generator = ComparisonReportGenerator(extracted_dir)
    report = generator.generate_report("2024-01")

    # 打印摘要
    generator.print_summary_report(report)

    # 保存完整报告
    output_path = script_dir / f"v1_v2_comparison_report_{Path(__file__).stem}.json"
    generator.save_report(report, output_path)

    # 生成Markdown报告
    md_path = script_dir / f"V1_V2_COMPARISON_REPORT.md"
    generate_markdown_report(report, md_path)
    logger.info(f"Markdown报告已保存到: {md_path}")


def generate_markdown_report(report: Dict, output_path: Path):
    """生成Markdown格式的报告"""
    lines = []

    lines.append("# InvariantGenerator V1 vs V2 对比报告\n")
    lines.append(f"生成时间: {Path(__file__).stem}\n")

    # 1. 执行摘要
    lines.append("## 执行摘要\n")
    summary = report["summary"]
    lines.append(f"- **总协议数**: {summary['total_protocols']}")
    lines.append(f"- **v1不变量总数**: {summary['v1_total_invariants']}")
    lines.append(f"- **v2不变量总数**: {summary['v2_total_invariants']}")

    if summary['v1_total_invariants'] > 0:
        improvement = (
            (summary['v2_total_invariants'] - summary['v1_total_invariants'])
            / summary['v1_total_invariants'] * 100
        )
        lines.append(f"- **整体改进**: {improvement:+.1f}%\n")

    # 2. 协议类型检测
    lines.append("## 协议类型检测能力\n")
    proto_comp = report["protocol_comparison"]
    lines.append("| 协议类型 | 检测数量 |")
    lines.append("|---------|---------|")
    for ptype, count in sorted(proto_comp["detected_types"].items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {ptype} | {count} |")
    lines.append(f"\n平均检测置信度: **{proto_comp['average_confidence']:.2%}**\n")

    # 3. 质量分析
    lines.append("## 质量分析\n")
    quality = report.get("quality_analysis", {})
    if quality:
        lines.append(f"- 平均质量得分: **{quality['average_score']:.2f}/100**")
        lines.append(f"- 最高得分: {quality['max_score']:.2f}")
        lines.append(f"- 最低得分: {quality['min_score']:.2f}\n")

        lines.append("### 得分分布\n")
        for level, count in quality["score_distribution"].items():
            lines.append(f"- {level}: {count} 个协议")
        lines.append("")

    # 4. 详细协议对比
    lines.append("## 详细协议对比\n")
    lines.append("| 协议名称 | 类型 | v1不变量 | v2不变量 | 攻击模式 | 质量得分 |")
    lines.append("|---------|------|---------|---------|---------|---------|")

    for proto in report["detailed_protocols"]:
        name = proto["name"]
        ptype = proto.get("protocol_type", "N/A")
        v1_count = proto.get("v1", {}).get("total_invariants", 0)
        v2_count = proto.get("v2", {}).get("total_invariants", 0)
        patterns = proto.get("v2", {}).get("attack_patterns_count", 0)
        score = proto["quality_score"]

        lines.append(f"| {name} | {ptype} | {v1_count} | {v2_count} | {patterns} | {score:.2f} |")

    lines.append("\n")

    # 5. 改进亮点
    lines.append("## V2版本改进亮点\n")
    lines.append("1. **协议类型自动检测**: 基于多源融合算法,平均置信度达到 "
                f"{proto_comp['average_confidence']:.2%}")
    lines.append("2. **攻击模式识别**: 自动检测10+种攻击模式(闪电贷、价格操纵、重入等)")
    lines.append("3. **语义槽位映射**: 自动识别32种存储槽位语义(totalSupply, balance等)")
    lines.append("4. **状态变化分析**: 量化分析合约状态变化幅度(7级变化等级)")
    lines.append("5. **模板驱动生成**: 针对不同协议类型使用18+种业务逻辑模板\n")

    # 写入文件
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


if __name__ == "__main__":
    main()
