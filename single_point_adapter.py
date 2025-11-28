#!/usr/bin/env python3
"""
单点状态适配器 - 解决v2.0受限问题

核心思路:
v2.0设计时假设有 before/after 状态差异,但实际数据只有单点快照。
本适配器让v2.0能够从单点状态生成不变量,方法是:
1. 基于槽位关系生成静态不变量(类似v1.0)
2. 使用协议模板生成业务逻辑不变量
3. 跳过依赖状态差异的功能

这是最实用的解决方案,无需修改数据收集脚本。
"""

import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).parent / "src" / "test"))

from invariant_toolkit import (
    ProtocolDetectorV2,
    SlotSemanticMapper,
    ComplexInvariantGenerator,
    BusinessLogicTemplates,
    StorageLayoutCalculator
)
from invariant_toolkit.protocol_detection import ProtocolType
from invariant_toolkit.storage_layout import SlotSemanticType
from invariant_toolkit.invariant_generation import InvariantCategory

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SinglePointStateAdapter:
    """
    适配器:从单点状态生成不变量

    核心策略:
    1. 分析单点状态的槽位语义
    2. 检测协议类型
    3. 根据协议类型+槽位语义生成业务逻辑不变量
    4. 生成槽位关系不变量(如 slot2/slot3 比率)
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.SinglePointStateAdapter')
        self.protocol_detector = ProtocolDetectorV2()
        self.slot_mapper = SlotSemanticMapper()
        self.template_lib = BusinessLogicTemplates()
        self.layout_calculator = StorageLayoutCalculator()

    def generate_from_single_point(
        self,
        project_dir: Path,
        output_path: Optional[Path] = None
    ) -> Dict:
        """
        从单点状态生成不变量

        Args:
            project_dir: 项目目录
            output_path: 输出路径

        Returns:
            生成结果字典
        """
        self.logger.info(f"开始处理项目(单点模式): {project_dir}")

        result = {
            "project": project_dir.name,
            "mode": "single_point_state",
            "protocol_type": None,
            "invariants": [],
            "statistics": {},
            "warnings": []
        }

        try:
            # 步骤1: 加载数据
            data = self._load_project_data(project_dir)

            # 步骤2: 检测协议类型
            protocol_result = self._detect_protocol(data, project_dir.name)
            result["protocol_type"] = protocol_result.detected_type.value
            result["protocol_confidence"] = protocol_result.confidence

            self.logger.info(
                f"  协议类型: {protocol_result.detected_type.value} "
                f"(置信度: {protocol_result.confidence:.2%})"
            )

            # 步骤3: 分析槽位语义
            semantic_mapping, slot_details = self._analyze_slots(data)
            result["semantic_mapping_coverage"] = self._calculate_coverage(semantic_mapping)

            # 步骤4: 生成不变量
            invariants = []

            # 4.1 基于模板生成(协议特定)
            template_invariants = self._generate_template_invariants(
                protocol_result.detected_type,
                semantic_mapping,
                slot_details,
                data
            )
            invariants.extend(template_invariants)
            self.logger.info(f"  生成了 {len(template_invariants)} 个模板不变量")

            # 4.2 基于槽位关系生成(通用)
            relation_invariants = self._generate_relation_invariants(
                slot_details,
                semantic_mapping
            )
            invariants.extend(relation_invariants)
            self.logger.info(f"  生成了 {len(relation_invariants)} 个关系不变量")

            # 4.3 基于跨合约关系生成
            cross_contract_invariants = self._generate_cross_contract_invariants(
                data,
                semantic_mapping,
                protocol_result.detected_type
            )
            invariants.extend(cross_contract_invariants)
            self.logger.info(f"  生成了 {len(cross_contract_invariants)} 个跨合约不变量")

            # 统计
            result["invariants"] = [asdict(inv) for inv in invariants]
            result["statistics"]["total_invariants"] = len(invariants)
            result["statistics"]["by_category"] = self._count_by_category(invariants)
            result["statistics"]["by_severity"] = self._count_by_severity(invariants)

            # 导出
            if output_path is None:
                output_path = project_dir / "invariants_v2_single_point.json"

            self._export_results(result, output_path)
            self.logger.info(f"结果已导出到: {output_path}")

        except Exception as e:
            self.logger.error(f"处理失败: {e}", exc_info=True)
            result["errors"] = [str(e)]

        return result

    def _load_project_data(self, project_dir: Path) -> Dict:
        """加载项目数据"""
        data = {}

        # 加载合约目录
        contract_dirs = [d for d in project_dir.iterdir() if d.is_dir() and d.name.startswith("0x")]
        if contract_dirs:
            data["main_contract_dir"] = contract_dirs[0]

            # 加载ABI
            abi_path = contract_dirs[0] / "abi.json"
            if abi_path.exists():
                with open(abi_path, 'r') as f:
                    data["abi"] = json.load(f)

        # 加载attack_state
        attack_state_path = project_dir / "attack_state.json"
        if attack_state_path.exists():
            with open(attack_state_path, 'r') as f:
                data["attack_state"] = json.load(f)

        # 加载addresses
        addresses_path = project_dir / "addresses.json"
        if addresses_path.exists():
            with open(addresses_path, 'r') as f:
                data["addresses"] = json.load(f)

        return data

    def _detect_protocol(self, data: Dict, project_name: str):
        """检测协议类型"""
        return self.protocol_detector.detect_with_confidence(
            contract_dir=data.get("main_contract_dir"),
            abi=data.get("abi"),
            project_name=project_name
        )

    def _analyze_slots(self, data: Dict):
        """分析槽位语义"""
        semantic_mapping = {}
        slot_details = {}  # 保存详细信息供生成不变量使用

        if "attack_state" not in data or "addresses" not in data["attack_state"]:
            return semantic_mapping, slot_details

        for address, state in data["attack_state"]["addresses"].items():
            if "storage" not in state:
                continue

            semantic_mapping[address] = {}
            slot_details[address] = []

            for slot, value in state["storage"].items():
                # 映射语义
                result = self.slot_mapper.map_variable_to_semantic(
                    variable_name=f"slot_{slot}",
                    value=value
                )

                semantic_type = result["semantic_type"]
                semantic_mapping[address][slot] = semantic_type.value

                # 保存详细信息
                slot_details[address].append({
                    "slot": slot,
                    "value": value,
                    "semantic": semantic_type,
                    "confidence": result["confidence"]
                })

        return semantic_mapping, slot_details

    def _generate_template_invariants(
        self,
        protocol_type: ProtocolType,
        semantic_mapping: Dict,
        slot_details: Dict,
        data: Dict
    ) -> List:
        """基于模板生成不变量"""
        from invariant_toolkit.invariant_generation import ComplexInvariant

        invariants = []
        templates = self.template_lib.get_templates_for_protocol(protocol_type)

        if not templates:
            return invariants

        self.logger.info(f"    尝试匹配 {len(templates)} 个 {protocol_type.value} 模板")

        # 尝试为每个模板找到匹配的槽位
        for template in templates:
            # 查找符合要求的槽位
            matched_slots = self._find_matching_slots(
                template.required_slots,
                slot_details
            )

            if matched_slots:
                # 生成不变量
                inv = ComplexInvariant(
                    id=f"SINV_{template.category.value}_{len(invariants):03d}",
                    type=template.name,
                    category=template.category.value,
                    description=template.description,
                    formula=template.formula_template.format(threshold=template.threshold),
                    threshold=template.threshold,
                    severity=template.severity,
                    contracts=list(matched_slots.keys()),
                    slots=matched_slots,
                    detection_confidence={
                        "template_match": 0.8,
                        "slot_semantic": 0.7
                    },
                    protocol_type=protocol_type.value,
                    attack_pattern=None
                )
                invariants.append(inv)

        return invariants

    def _find_matching_slots(self, required_semantics: List[str], slot_details: Dict) -> Dict:
        """查找匹配模板要求的槽位"""
        matched = {}

        for address, slots in slot_details.items():
            for slot_info in slots:
                semantic = slot_info["semantic"].value

                # 检查是否匹配所需语义
                for required in required_semantics:
                    if required.lower() in semantic.lower() or semantic.lower() in required.lower():
                        if address not in matched:
                            matched[address] = {}

                        matched[address][slot_info["slot"]] = {
                            "semantic": semantic,
                            "value": slot_info["value"]
                        }
                        break

        return matched if len(matched) > 0 else None

    def _generate_relation_invariants(self, slot_details: Dict, semantic_mapping: Dict) -> List:
        """基于槽位关系生成不变量(类似v1.0)"""
        from invariant_toolkit.invariant_generation import ComplexInvariant

        invariants = []

        # 对每个合约,找出重要槽位间的关系
        for address, slots in slot_details.items():
            # 查找totalSupply和balance相关槽位
            total_supply_slots = [s for s in slots if "supply" in s["semantic"].value.lower()]
            balance_slots = [s for s in slots if "balance" in s["semantic"].value.lower()]

            # 生成供应量守恒不变量
            if total_supply_slots:
                for ts_slot in total_supply_slots:
                    inv = ComplexInvariant(
                        id=f"RINV_supply_conservation_{len(invariants):03d}",
                        type="total_supply_conservation",
                        category=InvariantCategory.CONSERVATION.value,
                        description=f"总供应量在非铸造/销毁操作中应保持不变",
                        formula=f"slot_{ts_slot['slot']} == constant (except mint/burn)",
                        threshold=0.0,
                        severity="high",
                        contracts=[address],
                        slots={
                            ts_slot['slot']: {
                                "semantic": ts_slot['semantic'].value,
                                "baseline": ts_slot['value']
                            }
                        },
                        detection_confidence={"relation_heuristic": 0.7},
                        protocol_type=None,
                        attack_pattern=None
                    )
                    invariants.append(inv)

        return invariants

    def _generate_cross_contract_invariants(
        self,
        data: Dict,
        semantic_mapping: Dict,
        protocol_type: ProtocolType
    ) -> List:
        """生成跨合约不变量"""
        from invariant_toolkit.invariant_generation import ComplexInvariant

        invariants = []

        # 对于Vault协议,生成vault.totalAssets == underlying.balanceOf(vault)类型不变量
        if protocol_type == ProtocolType.VAULT:
            # TODO: 实现vault-underlying配对逻辑
            pass

        return invariants

    def _calculate_coverage(self, semantic_mapping: Dict) -> float:
        """计算语义覆盖率"""
        total_slots = 0
        mapped_slots = 0

        for contract_slots in semantic_mapping.values():
            total_slots += len(contract_slots)
            mapped_slots += sum(
                1 for semantic in contract_slots.values()
                if semantic != SlotSemanticType.UNKNOWN.value
            )

        return mapped_slots / total_slots if total_slots > 0 else 0.0

    def _count_by_category(self, invariants: List) -> Dict[str, int]:
        """按类别统计"""
        counts = {}
        for inv in invariants:
            category = inv.category
            counts[category] = counts.get(category, 0) + 1
        return counts

    def _count_by_severity(self, invariants: List) -> Dict[str, int]:
        """按严重性统计"""
        counts = {}
        for inv in invariants:
            severity = inv.severity
            counts[severity] = counts.get(severity, 0) + 1
        return counts

    def _export_results(self, result: Dict, output_path: Path):
        """导出结果"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)


def main():
    """测试单点适配器"""
    print("="*80)
    print(" 单点状态适配器 - 解决v2.0受限问题")
    print("="*80)
    print()

    adapter = SinglePointStateAdapter()

    # 测试协议
    test_protocols = [
        "BarleyFinance_exp",
        "XSIJ_exp",
        "MIC_exp"
    ]

    for protocol_name in test_protocols:
        project_dir = Path(f"extracted_contracts/2024-01/{protocol_name}")

        if not project_dir.exists():
            print(f"⚠️  跳过不存在的项目: {protocol_name}")
            continue

        print(f"\n{'='*80}")
        print(f"处理: {protocol_name}")
        print(f"{'='*80}\n")

        result = adapter.generate_from_single_point(project_dir)

        # 显示结果
        print(f"\n📊 生成结果:")
        print(f"  协议类型: {result.get('protocol_type', 'unknown')}")
        print(f"  置信度: {result.get('protocol_confidence', 0):.2%}")
        print(f"  语义覆盖率: {result.get('semantic_mapping_coverage', 0):.2%}")

        stats = result.get("statistics", {})
        print(f"\n✅ 不变量统计:")
        print(f"  总数: {stats.get('total_invariants', 0)}")

        if stats.get('by_category'):
            print(f"\n  按类别:")
            for cat, count in stats['by_category'].items():
                print(f"    {cat}: {count}")

        if stats.get('by_severity'):
            print(f"\n  按严重性:")
            for sev, count in sorted(stats['by_severity'].items(), reverse=True):
                print(f"    {sev}: {count}")

        # 显示前3个不变量
        invariants = result.get("invariants", [])
        if invariants:
            print(f"\n📋 不变量示例 (前3个):")
            for i, inv in enumerate(invariants[:3], 1):
                print(f"\n  {i}. {inv['type']} ({inv['category']})")
                print(f"     {inv['description'][:70]}...")
                print(f"     严重性: {inv['severity']}")

    print("\n" + "="*80)
    print("✅ 处理完成!")
    print("="*80)


if __name__ == "__main__":
    main()
