"""
复杂不变量生成器

基于协议类型、状态差异和模式检测,生成跨合约、多变量的业务逻辑不变量。
"""

import logging
import json
import re
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..protocol_detection import ProtocolType
from ..storage_layout import SlotSemanticType
from ..state_analysis import DiffReport, ChangePattern
from .business_logic_templates import BusinessLogicTemplates, InvariantTemplate, InvariantCategory
from .cross_contract_analyzer import CrossContractAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class SlotReference:
    """槽位引用"""
    contract: str
    slot: str
    semantic_type: str
    variable_name: Optional[str] = None
    derived_from: str = "manual"  # "abi_analysis", "mapping_calculation", "manual"


@dataclass
class ComplexInvariant:
    """复杂不变量"""
    id: str
    type: str  # cross_contract_ratio_stability, share_price_monotonic等
    category: str  # ratio_stability, monotonicity等
    description: str
    formula: str
    threshold: float
    severity: str

    # 涉及的合约和槽位
    contracts: List[str] = field(default_factory=list)
    slots: Dict[str, SlotReference] = field(default_factory=dict)

    # 检测置信度
    detection_confidence: Dict[str, float] = field(default_factory=dict)

    # 元数据
    protocol_type: Optional[str] = None
    attack_pattern: Optional[str] = None  # 对应的攻击模式


class ComplexInvariantGenerator:
    """
    复杂不变量生成器

    整合所有分析结果,生成高质量的业务逻辑不变量。
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.ComplexInvariantGenerator')
        self.cross_contract_analyzer = CrossContractAnalyzer()
        self._pattern_id_counters = {}  # 用于生成唯一ID

    def generate_invariants(
        self,
        protocol_type: ProtocolType,
        storage_layout: Dict[str, Dict[str, any]],  # contract -> {slot -> semantic_info}
        diff_report: Optional[DiffReport] = None,
        patterns: Optional[List[ChangePattern]] = None,
        semantic_mapping: Optional[Dict[str, Dict[str, str]]] = None
    ) -> List[ComplexInvariant]:
        """
        生成复杂不变量

        Args:
            protocol_type: 协议类型
            storage_layout: 存储布局信息
            diff_report: 状态差异报告
            patterns: 检测到的模式
            semantic_mapping: 槽位语义映射

        Returns:
            ComplexInvariant列表
        """
        self.logger.info(f"开始生成 {protocol_type.value} 协议的复杂不变量...")

        invariants = []

        # 1. 获取协议特定的模板
        templates = BusinessLogicTemplates.get_templates_for_protocol(protocol_type)
        self.logger.debug(f"加载了 {len(templates)} 个模板")

        # 2. 根据存储布局和模板生成不变量
        for template in templates:
            generated = self._generate_from_template(
                template,
                storage_layout,
                semantic_mapping or {}
            )
            invariants.extend(generated)

        # 3. 基于检测到的攻击模式生成防御性不变量
        if patterns:
            pattern_invariants = self._generate_from_patterns(
                patterns,
                storage_layout,
                protocol_type
            )
            invariants.extend(pattern_invariants)

        # 4. 基于跨合约关系生成不变量
        if diff_report:
            cross_contract_invariants = self._generate_cross_contract_invariants(
                diff_report,
                storage_layout,
                protocol_type
            )
            invariants.extend(cross_contract_invariants)

        self.logger.info(f"生成完成: 共 {len(invariants)} 个不变量")

        return invariants

    def _generate_from_template(
        self,
        template: InvariantTemplate,
        storage_layout: Dict[str, Dict[str, any]],
        semantic_mapping: Dict[str, Dict[str, str]]
    ) -> List[ComplexInvariant]:
        """从模板生成不变量"""

        invariants = []

        # 检查是否有所需的槽位
        required_slots_found = self._find_required_slots(
            template.required_slots,
            storage_layout,
            semantic_mapping
        )

        if not required_slots_found:
            self.logger.debug(f"模板 {template.name} 缺少必需槽位,跳过")
            return []

        # 为每个匹配的合约生成不变量
        for contract_addr, slots in required_slots_found.items():
            # 构建槽位引用
            slot_refs = {}
            for semantic_type, slot in slots.items():
                slot_refs[semantic_type] = SlotReference(
                    contract=contract_addr,
                    slot=slot,
                    semantic_type=semantic_type,
                    derived_from="semantic_mapping"
                )

            # 替换公式中的占位符
            formula = template.formula_template.format(threshold=template.threshold)

            # 生成不变量ID
            inv_id = f"SINV_{template.category.value}_{len(invariants):03d}"

            invariant = ComplexInvariant(
                id=inv_id,
                type=template.name,
                category=template.category.value,
                description=template.description,
                formula=formula,
                threshold=template.threshold,
                severity=template.severity,
                contracts=[contract_addr],
                slots=slot_refs,
                detection_confidence={
                    "slot_semantic": 0.9,
                    "template_match": 0.95
                }
            )

            invariants.append(invariant)

        return invariants

    def _find_required_slots(
        self,
        required_semantics: List[str],
        storage_layout: Dict[str, Dict[str, any]],
        semantic_mapping: Dict[str, Dict[str, str]]
    ) -> Dict[str, Dict[str, str]]:
        """
        查找所需的槽位

        Returns:
            {contract_address: {semantic_type: slot}}
        """
        found = {}

        for contract_addr, mapping in semantic_mapping.items():
            contract_slots = {}

            for slot, semantic_type in mapping.items():
                # 检查是否匹配所需语义
                for required in required_semantics:
                    if required.lower() in semantic_type.lower():
                        contract_slots[semantic_type] = slot

            # 检查是否找到所有必需槽位
            if len(contract_slots) >= len(required_semantics):
                found[contract_addr] = contract_slots

        return found

    def _generate_from_patterns(
        self,
        patterns: List[ChangePattern],
        storage_layout: Dict[str, Dict[str, any]],
        protocol_type: ProtocolType
    ) -> List[ComplexInvariant]:
        """基于检测到的攻击模式生成防御性不变量"""

        invariants = []
        # 重置ID计数器
        self._pattern_id_counters = {}

        for pattern in patterns:
            if pattern.severity in ["critical", "high"]:
                # 生成针对性的不变量
                inv = self._create_pattern_based_invariant(pattern, protocol_type)
                if inv:
                    invariants.append(inv)

        return invariants

    def _get_next_pattern_id(self, pattern_type: str) -> str:
        """
        为指定模式类型生成下一个唯一ID

        Args:
            pattern_type: 模式类型 (如 "flash_change")

        Returns:
            唯一ID (如 "PATTERN_flash_change_001", "PATTERN_flash_change_002")
        """
        if pattern_type not in self._pattern_id_counters:
            self._pattern_id_counters[pattern_type] = 0

        self._pattern_id_counters[pattern_type] += 1
        counter = self._pattern_id_counters[pattern_type]

        return f"PATTERN_{pattern_type}_{counter:03d}"

    def _extract_change_rate_from_evidence(self, evidence: List[str]) -> float:
        """
        从evidence列表中提取最大变化率

        Evidence格式示例:
        - "Slot 8: 1234x change"
        - "Slot 9: +156.78%"

        Returns:
            最大变化率(绝对值), 如果无法提取则返回None
        """
        max_rate = 0.0

        for ev in evidence:
            # 匹配 "NNNx change" 格式 (如 "1234x change")
            match_x = re.search(r'(\d+(?:\.\d+)?)\s*x\s*change', ev, re.IGNORECASE)
            if match_x:
                rate = float(match_x.group(1))
                max_rate = max(max_rate, rate)
                continue

            # 匹配百分比格式 (如 "+156.78%" 或 "-50.00%")
            match_pct = re.search(r'[+-]?(\d+(?:\.\d+)?)\s*%', ev)
            if match_pct:
                rate = float(match_pct.group(1)) / 100.0  # 转换为倍数
                max_rate = max(max_rate, rate)

        return max_rate if max_rate > 0 else 0.0

    def _calculate_dynamic_threshold(
        self,
        pattern: ChangePattern,
        protocol_type: ProtocolType
    ) -> Tuple[float, str]:
        """
        基于实际数据计算动态阈值

        Args:
            pattern: 变化模式，包含evidence列表
            protocol_type: 协议类型

        Returns:
            (threshold, formula) 元组
        """
        # 从evidence中提取实际变化率
        actual_change_rate = self._extract_change_rate_from_evidence(pattern.evidence)

        # 如果无法提取，使用基于协议类型的默认值
        if actual_change_rate <= 0:
            return self._get_default_threshold_for_protocol(protocol_type, pattern.pattern_type.value)

        # 动态计算阈值策略：
        # 1. 对于闪电贷攻击(通常变化率>10x)，阈值设为实际变化率的10%
        # 2. 对于中等变化(1x-10x)，阈值设为实际变化率的50%
        # 3. 对于小变化(<1x即<100%)，阈值设为实际变化率的80%

        if actual_change_rate >= 10.0:  # 1000%+ 变化 (闪电贷特征)
            threshold = max(0.5, actual_change_rate * 0.1)  # 最低50%
            threshold = min(threshold, 5.0)  # 最高500%
        elif actual_change_rate >= 1.0:  # 100%-1000% 变化
            threshold = max(0.2, actual_change_rate * 0.5)  # 最低20%
            threshold = min(threshold, 2.0)  # 最高200%
        else:  # <100% 变化
            threshold = max(0.05, actual_change_rate * 0.8)  # 最低5%
            threshold = min(threshold, 0.5)  # 最高50%

        # 四舍五入到2位小数
        threshold = round(threshold, 2)

        formula = f"abs(value_after - value_before) / value_before <= {threshold}"

        return threshold, formula

    def _get_default_threshold_for_protocol(
        self,
        protocol_type: ProtocolType,
        pattern_type: str
    ) -> Tuple[float, str]:
        """
        根据协议类型和模式类型获取默认阈值

        不同协议有不同的正常波动范围
        """
        # 协议类型默认阈值
        protocol_defaults = {
            ProtocolType.LENDING: 0.1,          # 借贷协议: 10%
            ProtocolType.AMM: 0.3,              # AMM: 30% (流动性变化大)
            ProtocolType.VAULT: 0.15,           # Vault: 15%
            ProtocolType.STAKING: 0.2,          # 质押: 20%
            ProtocolType.BRIDGE: 0.05,          # 跨链桥: 5% (应该很稳定)
            ProtocolType.ERC20: 0.5,            # 代币: 50% (交易波动大)
            ProtocolType.GOVERNANCE: 0.1,       # 治理: 10%
            ProtocolType.NFT_MARKETPLACE: 0.3,  # NFT市场: 30%
            ProtocolType.UNKNOWN: 0.2,          # 未知: 20%
        }

        # 模式类型调整因子
        pattern_adjustments = {
            "flash_change": 0.5,        # 闪电贷: 降低阈值(更严格)
            "flash_mint": 0.3,
            "price_manipulation": 0.7,
            "ratio_break": 0.6,
            "monotonic_increase": 0.8,
            "reentrancy_balance": 0.5,
            "massive_transfer": 0.4,
        }

        # 获取基础阈值
        base_threshold = protocol_defaults.get(protocol_type, 0.2)

        # 应用模式调整
        adjustment = pattern_adjustments.get(pattern_type, 1.0)
        threshold = round(base_threshold * adjustment, 2)

        # 确保阈值在合理范围内
        threshold = max(0.01, min(threshold, 1.0))

        formula = f"abs(value_after - value_before) / value_before <= {threshold}"

        return threshold, formula

    def _create_pattern_based_invariant(
        self,
        pattern: ChangePattern,
        protocol_type: ProtocolType
    ) -> Optional[ComplexInvariant]:
        """
        从模式创建不变量

        支持的攻击模式:
        - flash_change: 闪电贷极端变化
        - ratio_break: 比率关系破坏
        - monotonic_increase: 单调递增异常
        - reentrancy_balance: 重入余额异常
        - zero_value_change: 从零突变
        - massive_transfer: 巨额转账
        """

        pattern_type = pattern.pattern_type.value

        # 生成唯一ID
        unique_id = self._get_next_pattern_id(pattern_type)

        # 计算动态阈值
        threshold, formula = self._calculate_dynamic_threshold(pattern, protocol_type)

        # 构建slots信息字典
        slots_dict = self._build_slots_dict_from_pattern(pattern, threshold)

        # 根据模式类型生成对应的不变量
        if "flash" in pattern_type:
            # 闪电贷模式 -> 限制极端变化
            return ComplexInvariant(
                id=unique_id,
                type="flash_change_prevention",
                category="bounded_value",
                description=f"Prevent extreme value changes (flash loan attack)",
                formula=formula,
                threshold=threshold,
                severity="critical",
                contracts=pattern.contracts,
                slots=slots_dict,
                attack_pattern=pattern_type,
                detection_confidence={"pattern_match": pattern.confidence}
            )

        elif pattern_type == "ratio_break":
            # 比率破坏模式 -> 比率稳定性约束
            return ComplexInvariant(
                id=unique_id,
                type="ratio_stability",
                category="ratio_bound",
                description=f"Ensure ratio stability between related values",
                formula=f"abs(ratio_after - ratio_before) / ratio_before <= {threshold}",
                threshold=threshold,
                severity="high",
                contracts=pattern.contracts,
                slots=slots_dict,
                attack_pattern=pattern_type,
                detection_confidence={"pattern_match": pattern.confidence}
            )

        elif pattern_type == "monotonic_increase":
            # 单调递增模式 -> 增长率上限
            return ComplexInvariant(
                id=unique_id,
                type="growth_rate_limit",
                category="bounded_growth",
                description=f"Limit abnormal value growth rate",
                formula=f"(value_after - value_before) / value_before <= {threshold}",
                threshold=threshold,
                severity="high",
                contracts=pattern.contracts,
                slots=slots_dict,
                attack_pattern=pattern_type,
                detection_confidence={"pattern_match": pattern.confidence}
            )

        elif pattern_type == "reentrancy_balance":
            # 重入余额模式 -> 余额变化限制
            return ComplexInvariant(
                id=unique_id,
                type="balance_change_limit",
                category="bounded_value",
                description=f"Limit balance changes to prevent reentrancy attacks",
                formula=f"abs(balance_after - balance_before) / balance_before <= {threshold}",
                threshold=threshold,
                severity="high",
                contracts=pattern.contracts,
                slots=slots_dict,
                attack_pattern=pattern_type,
                detection_confidence={"pattern_match": pattern.confidence}
            )

        elif pattern_type == "zero_value_change":
            # 从零突变模式 -> 初始化值限制
            max_initial = self._calculate_max_initial_value(pattern)
            return ComplexInvariant(
                id=unique_id,
                type="initialization_limit",
                category="value_range",
                description=f"Limit value initialization from zero",
                formula=f"value_after <= {max_initial} when value_before == 0",
                threshold=float(max_initial),
                severity="medium",
                contracts=pattern.contracts,
                slots=slots_dict,
                attack_pattern=pattern_type,
                detection_confidence={"pattern_match": pattern.confidence}
            )

        elif pattern_type == "massive_transfer":
            # 巨额转账模式 -> 转账额度限制
            return ComplexInvariant(
                id=unique_id,
                type="transfer_limit",
                category="bounded_value",
                description=f"Limit massive token transfers",
                formula=f"transfer_amount / total_supply <= {threshold}",
                threshold=threshold,
                severity="medium",
                contracts=pattern.contracts,
                slots=slots_dict,
                attack_pattern=pattern_type,
                detection_confidence={"pattern_match": pattern.confidence}
            )

        elif pattern_type == "price_manipulation":
            # 价格操纵模式 -> 价格变化限制
            return ComplexInvariant(
                id=unique_id,
                type="price_change_limit",
                category="bounded_value",
                description=f"Limit price manipulation attacks",
                formula=f"abs(price_after - price_before) / price_before <= {threshold}",
                threshold=threshold,
                severity="critical",
                contracts=pattern.contracts,
                slots=slots_dict,
                attack_pattern=pattern_type,
                detection_confidence={"pattern_match": pattern.confidence}
            )

        elif pattern_type == "ownership_change":
            # 所有权变更模式 -> 所有权保护
            return ComplexInvariant(
                id=unique_id,
                type="ownership_protection",
                category="access_control",
                description=f"Protect against unauthorized ownership changes",
                formula=f"owner_after == owner_before OR authorized_change",
                threshold=0.0,  # 不允许未授权变更
                severity="critical",
                contracts=pattern.contracts,
                slots=slots_dict,
                attack_pattern=pattern_type,
                detection_confidence={"pattern_match": pattern.confidence}
            )

        # 对于未知模式，使用通用变化限制
        self.logger.debug(f"未知模式类型 {pattern_type}，使用通用不变量")
        return ComplexInvariant(
            id=unique_id,
            type="generic_change_limit",
            category="bounded_value",
            description=f"Generic change limit for {pattern_type} pattern",
            formula=formula,
            threshold=threshold,
            severity=pattern.severity,
            contracts=pattern.contracts,
            slots=slots_dict,
            attack_pattern=pattern_type,
            detection_confidence={"pattern_match": pattern.confidence}
        )

    def _calculate_max_initial_value(self, pattern: ChangePattern) -> int:
        """
        计算从零突变时允许的最大初始值

        基于evidence中的实际值计算合理上限
        """
        max_value = 10 ** 18  # 默认1e18 (1 token with 18 decimals)

        for ev in pattern.evidence:
            # 尝试从evidence中提取实际值
            match = re.search(r'0\s*->\s*(\d+)', ev)
            if match:
                actual_value = int(match.group(1))
                # 设置为实际值的80%作为上限
                max_value = min(max_value, int(actual_value * 0.8))

        return max(max_value, 10 ** 6)  # 最少1e6

    def _build_slots_dict_from_pattern(self, pattern: ChangePattern, threshold: float = 0.05) -> Dict:
        """
        从ChangePattern构建slots字典

        优化策略:
        1. 优先选择简单slot索引(0-100)而不是mapping键
        2. 对于Uniswap V2等DEX,优先选择slot 8和9(reserves)
        3. 使用传入的动态阈值

        Args:
            pattern: 包含slots列表的变化模式
            threshold: 动态计算的阈值

        Returns:
            格式化的slots字典，用于不变量定义
        """
        slots_dict = {}

        if pattern.slots:
            # 将slots分为简单索引和复杂mapping键
            simple_slots = []
            complex_slots = []

            for slot in pattern.slots:
                try:
                    slot_int = int(slot)
                    # 简单slot: 数值小于1000
                    if slot_int < 1000:
                        simple_slots.append(slot)
                    else:
                        complex_slots.append(slot)
                except (ValueError, TypeError):
                    complex_slots.append(slot)

            # 优先使用简单slots
            preferred_slots = simple_slots if simple_slots else complex_slots

            # 对于DEX/流动性池,特别优先使用slot 8和9(Uniswap V2 reserves)
            if "8" in simple_slots or "9" in simple_slots:
                # 只保留slot 8和9
                preferred_slots = [s for s in simple_slots if s in ["8", "9"]]
                # 如果只有其中一个,保留两个
                if len(preferred_slots) < 2:
                    if "8" in simple_slots:
                        preferred_slots = ["8"]
                    if "9" in simple_slots:
                        if "8" not in preferred_slots:
                            preferred_slots = ["9"]
                        else:
                            preferred_slots = ["8", "9"]

            # 构建slots字典
            for i, slot in enumerate(preferred_slots):
                # 为简单slot使用语义化的名称
                try:
                    slot_int = int(slot)
                    if slot_int == 8:
                        slot_key = "reserve0_slot"
                    elif slot_int == 9:
                        slot_key = "reserve1_slot"
                    elif slot_int < 100:
                        slot_key = f"slot_{slot}"
                    else:
                        slot_key = f"slot_{i}"
                except:
                    slot_key = f"slot_{i}"

                slots_dict[slot_key] = {
                    "index": slot,
                    "threshold": threshold,  # 使用动态阈值
                    "severity": pattern.severity
                }

        return slots_dict

    def _generate_cross_contract_invariants(
        self,
        diff_report: DiffReport,
        storage_layout: Dict[str, Dict[str, any]],
        protocol_type: ProtocolType
    ) -> List[ComplexInvariant]:
        """生成跨合约不变量"""

        invariants = []

        # 分析跨合约关系
        relationships = self.cross_contract_analyzer.analyze_relationships(
            contracts=storage_layout,
            diff_report=diff_report
        )

        # 根据关系生成不变量
        for relation in relationships:
            if relation.relation_type == "balance_transfer":
                # 余额转移守恒
                inv = ComplexInvariant(
                    id=f"CROSS_balance_conservation",
                    type="balance_conservation",
                    category="conservation",
                    description="Balance transfer conservation between contracts",
                    formula=f"abs(balance_change_A + balance_change_B) <= gas_tolerance",
                    threshold=0.01,
                    severity="high",
                    contracts=[relation.contract_a, relation.contract_b],
                    slots={},
                    detection_confidence={"relation_confidence": relation.confidence}
                )
                invariants.append(inv)

        return invariants

    def export_to_json(
        self,
        invariants: List[ComplexInvariant],
        output_path: Path
    ) -> None:
        """导出不变量到JSON文件"""

        invariants_dict = {
            "storage_invariants": [],
            "runtime_invariants": [],
            "metadata": {
                "total_count": len(invariants),
                "generator_version": "2.0.0"
            }
        }

        for inv in invariants:
            inv_dict = asdict(inv)
            invariants_dict["storage_invariants"].append(inv_dict)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(invariants_dict, f, indent=2, ensure_ascii=False)

        self.logger.info(f"不变量已导出到: {output_path}")

    def get_summary(self, invariants: List[ComplexInvariant]) -> str:
        """生成不变量摘要"""

        lines = [
            "=== Invariant Generation Summary ===",
            f"Total invariants: {len(invariants)}",
            ""
        ]

        # 按类别分组
        by_category = {}
        for inv in invariants:
            category = inv.category
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(inv)

        for category, invs in sorted(by_category.items()):
            lines.append(f"{category}: {len(invs)} invariants")
            for inv in invs[:2]:  # 显示前2个
                lines.append(f"  - {inv.type}: {inv.description[:60]}...")

        return "\n".join(lines)
