"""
状态差异计算器

深度分析attack_state.json中before/after状态的差异,
提供槽位级别的变化分析、异常检测和跨合约关联分析。
"""

import logging
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

logger = logging.getLogger(__name__)


class ChangeDirection(Enum):
    """变化方向"""
    INCREASE = "increase"
    DECREASE = "decrease"
    NO_CHANGE = "no_change"
    NEW_VALUE = "new_value"        # 之前不存在
    REMOVED_VALUE = "removed_value"  # 之后不存在


class ChangeMagnitude(Enum):
    """变化幅度等级"""
    NONE = "none"           # 无变化
    TINY = "tiny"           # < 0.1%
    SMALL = "small"         # 0.1% - 1%
    MEDIUM = "medium"       # 1% - 10%
    LARGE = "large"         # 10% - 50%
    MASSIVE = "massive"     # 50% - 1000%
    EXTREME = "extreme"     # > 1000% (闪电贷特征)


@dataclass
class ContractState:
    """合约状态"""
    address: str
    storage: Dict[str, str]  # slot -> value (hex string)
    balance: str = "0x0"
    nonce: int = 0
    code: Optional[str] = None


@dataclass
class SlotChange:
    """单个槽位的变化"""
    slot: str
    value_before: Optional[str]
    value_after: Optional[str]

    # 计算字段
    direction: ChangeDirection = ChangeDirection.NO_CHANGE
    magnitude: ChangeMagnitude = ChangeMagnitude.NONE
    change_rate: float = 0.0  # 变化率 (相对值)
    absolute_change: int = 0  # 绝对变化量

    # 语义信息
    semantic_type: Optional[str] = None
    variable_name: Optional[str] = None


@dataclass
class ContractDiff:
    """单个合约的差异"""
    address: str
    slot_changes: List[SlotChange] = field(default_factory=list)
    balance_change: int = 0
    nonce_change: int = 0

    # 统计信息
    total_slots_changed: int = 0
    slots_increased: int = 0
    slots_decreased: int = 0
    new_slots: int = 0
    removed_slots: int = 0


@dataclass
class CrossContractRelation:
    """跨合约关系"""
    relation_type: str  # "balance_transfer", "ratio_change", "causality"
    contracts: List[str]
    slots: List[str]
    description: str
    correlation_score: float = 0.0


@dataclass
class DiffReport:
    """完整的差异报告"""
    contract_diffs: Dict[str, ContractDiff]  # address -> ContractDiff
    cross_contract_relations: List[CrossContractRelation] = field(default_factory=list)

    # 全局统计
    total_contracts_changed: int = 0
    total_slots_changed: int = 0
    extreme_changes: List[SlotChange] = field(default_factory=list)  # 极端变化

    # 异常检测
    anomalies: List[str] = field(default_factory=list)


class StateDiffCalculator:
    """
    状态差异计算器

    分析attack_state.json中的before和after状态,
    计算槽位级别的变化、识别异常模式、检测跨合约关联。
    """

    # 变化幅度阈值
    MAGNITUDE_THRESHOLDS = {
        ChangeMagnitude.TINY: 0.001,      # 0.1%
        ChangeMagnitude.SMALL: 0.01,      # 1%
        ChangeMagnitude.MEDIUM: 0.1,      # 10%
        ChangeMagnitude.LARGE: 0.5,       # 50%
        ChangeMagnitude.MASSIVE: 10.0,    # 1000%
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.StateDiffCalculator')

    def compute_comprehensive_diff(
        self,
        before: Dict[str, ContractState],
        after: Dict[str, ContractState],
        semantic_mapping: Optional[Dict[str, Dict[str, str]]] = None
    ) -> DiffReport:
        """
        计算完整的状态差异

        Args:
            before: 攻击前状态 {address: ContractState}
            after: 攻击后状态 {address: ContractState}
            semantic_mapping: 槽位语义映射 {address: {slot: semantic_type}}

        Returns:
            DiffReport对象,包含详细的差异分析
        """
        self.logger.info(f"开始计算状态差异: {len(before)} 个合约(before) vs {len(after)} 个合约(after)")

        contract_diffs = {}
        all_addresses = set(before.keys()) | set(after.keys())

        # 计算每个合约的差异
        for address in all_addresses:
            before_state = before.get(address)
            after_state = after.get(address)

            diff = self._compute_contract_diff(
                address,
                before_state,
                after_state,
                semantic_mapping.get(address) if semantic_mapping else None
            )

            if diff.total_slots_changed > 0 or diff.balance_change != 0:
                contract_diffs[address] = diff

        # 识别跨合约关系
        cross_relations = self._detect_cross_contract_relations(
            before, after, contract_diffs
        )

        # 收集极端变化和异常
        extreme_changes = []
        anomalies = []

        for diff in contract_diffs.values():
            for slot_change in diff.slot_changes:
                if slot_change.magnitude in [ChangeMagnitude.MASSIVE, ChangeMagnitude.EXTREME]:
                    extreme_changes.append(slot_change)
                    anomalies.append(
                        f"Extreme change in {diff.address[:10]}... slot {slot_change.slot}: "
                        f"{slot_change.magnitude.value} ({slot_change.change_rate:.2%})"
                    )

        self.logger.info(
            f"差异计算完成: {len(contract_diffs)} 个合约有变化, "
            f"{sum(d.total_slots_changed for d in contract_diffs.values())} 个槽位变化"
        )

        return DiffReport(
            contract_diffs=contract_diffs,
            cross_contract_relations=cross_relations,
            total_contracts_changed=len(contract_diffs),
            total_slots_changed=sum(d.total_slots_changed for d in contract_diffs.values()),
            extreme_changes=extreme_changes,
            anomalies=anomalies
        )

    def _compute_contract_diff(
        self,
        address: str,
        before: Optional[ContractState],
        after: Optional[ContractState],
        semantic_mapping: Optional[Dict[str, str]] = None
    ) -> ContractDiff:
        """计算单个合约的差异"""

        slot_changes = []

        # 获取所有槽位
        before_storage = before.storage if before else {}
        after_storage = after.storage if after else {}
        all_slots = set(before_storage.keys()) | set(after_storage.keys())

        # 计算每个槽位的变化
        for slot in all_slots:
            value_before = before_storage.get(slot)
            value_after = after_storage.get(slot)

            if value_before == value_after:
                continue  # 无变化,跳过

            slot_change = self._compute_slot_change(
                slot,
                value_before,
                value_after,
                semantic_mapping.get(slot) if semantic_mapping else None
            )

            slot_changes.append(slot_change)

        # 计算余额和nonce变化
        balance_before = int(before.balance, 16) if before and before.balance else 0
        balance_after = int(after.balance, 16) if after and after.balance else 0
        balance_change = balance_after - balance_before

        nonce_before = before.nonce if before else 0
        nonce_after = after.nonce if after else 0
        nonce_change = nonce_after - nonce_before

        # 统计
        slots_increased = sum(1 for sc in slot_changes if sc.direction == ChangeDirection.INCREASE)
        slots_decreased = sum(1 for sc in slot_changes if sc.direction == ChangeDirection.DECREASE)
        new_slots = sum(1 for sc in slot_changes if sc.direction == ChangeDirection.NEW_VALUE)
        removed_slots = sum(1 for sc in slot_changes if sc.direction == ChangeDirection.REMOVED_VALUE)

        return ContractDiff(
            address=address,
            slot_changes=slot_changes,
            balance_change=balance_change,
            nonce_change=nonce_change,
            total_slots_changed=len(slot_changes),
            slots_increased=slots_increased,
            slots_decreased=slots_decreased,
            new_slots=new_slots,
            removed_slots=removed_slots
        )

    def _compute_slot_change(
        self,
        slot: str,
        value_before: Optional[str],
        value_after: Optional[str],
        semantic_type: Optional[str] = None
    ) -> SlotChange:
        """计算单个槽位的变化详情"""

        def _parse_hex_or_int(value: str) -> int:
            """解析十六进制或十进制字符串"""
            if value.startswith('0x') or value.startswith('0X'):
                return int(value, 16)
            # 检查是否全是十六进制字符(0-9a-f)
            elif all(c in '0123456789abcdefABCDEF' for c in value):
                return int(value, 16)  # 按十六进制解析
            else:
                return int(value)  # 按十进制解析

        # 确定变化方向
        if value_before is None:
            direction = ChangeDirection.NEW_VALUE
        elif value_after is None:
            direction = ChangeDirection.REMOVED_VALUE
        else:
            # 转换为整数比较
            int_before = _parse_hex_or_int(value_before)
            int_after = _parse_hex_or_int(value_after)

            if int_after > int_before:
                direction = ChangeDirection.INCREASE
            elif int_after < int_before:
                direction = ChangeDirection.DECREASE
            else:
                direction = ChangeDirection.NO_CHANGE

        # 计算变化率和绝对变化量
        change_rate = 0.0
        absolute_change = 0
        magnitude = ChangeMagnitude.NONE

        if direction not in [ChangeDirection.NO_CHANGE, ChangeDirection.NEW_VALUE, ChangeDirection.REMOVED_VALUE]:
            int_before = _parse_hex_or_int(value_before)
            int_after = _parse_hex_or_int(value_after)

            absolute_change = int_after - int_before

            # 计算变化率 (避免除零)
            if int_before != 0:
                change_rate = abs(absolute_change / int_before)
            else:
                # 从0变化到非0,视为极端变化
                change_rate = float('inf') if int_after != 0 else 0.0

            # 确定变化幅度
            magnitude = self._classify_magnitude(change_rate)

        return SlotChange(
            slot=slot,
            value_before=value_before,
            value_after=value_after,
            direction=direction,
            magnitude=magnitude,
            change_rate=change_rate,
            absolute_change=absolute_change,
            semantic_type=semantic_type
        )

    def _classify_magnitude(self, change_rate: float) -> ChangeMagnitude:
        """分类变化幅度"""
        abs_rate = abs(change_rate)

        if abs_rate == 0:
            return ChangeMagnitude.NONE
        elif abs_rate < self.MAGNITUDE_THRESHOLDS[ChangeMagnitude.TINY]:
            return ChangeMagnitude.TINY
        elif abs_rate < self.MAGNITUDE_THRESHOLDS[ChangeMagnitude.SMALL]:
            return ChangeMagnitude.SMALL
        elif abs_rate < self.MAGNITUDE_THRESHOLDS[ChangeMagnitude.MEDIUM]:
            return ChangeMagnitude.MEDIUM
        elif abs_rate < self.MAGNITUDE_THRESHOLDS[ChangeMagnitude.LARGE]:
            return ChangeMagnitude.LARGE
        elif abs_rate < self.MAGNITUDE_THRESHOLDS[ChangeMagnitude.MASSIVE]:
            return ChangeMagnitude.MASSIVE
        else:
            return ChangeMagnitude.EXTREME

    def _detect_cross_contract_relations(
        self,
        before: Dict[str, ContractState],
        after: Dict[str, ContractState],
        contract_diffs: Dict[str, ContractDiff]
    ) -> List[CrossContractRelation]:
        """
        检测跨合约关系

        识别模式:
        1. 余额转移: A减少 & B增加,且数量相等
        2. 比率变化: Vault的totalSupply与underlying的balance比率
        3. 因果关系: 时间上相关的变化
        """
        relations = []

        # 1. 检测余额转移
        balance_changes = {}
        for address, diff in contract_diffs.items():
            if diff.balance_change != 0:
                balance_changes[address] = diff.balance_change

        # 寻找配对的余额变化
        addresses = list(balance_changes.keys())
        for i, addr1 in enumerate(addresses):
            for addr2 in addresses[i+1:]:
                change1 = balance_changes[addr1]
                change2 = balance_changes[addr2]

                # 一增一减,且金额接近 (允许gas费误差)
                if change1 * change2 < 0 and abs(abs(change1) - abs(change2)) < abs(change1) * 0.01:
                    relations.append(CrossContractRelation(
                        relation_type="balance_transfer",
                        contracts=[addr1, addr2],
                        slots=["balance", "balance"],
                        description=f"Balance transfer: {abs(change1)} wei from {addr1[:10]}... to {addr2[:10]}...",
                        correlation_score=0.95
                    ))

        # 2. 检测存储槽位相关变化
        # 寻找同时发生的大幅度变化
        extreme_changes_by_contract = {}
        for address, diff in contract_diffs.items():
            extreme_slots = [
                sc for sc in diff.slot_changes
                if sc.magnitude in [ChangeMagnitude.LARGE, ChangeMagnitude.MASSIVE, ChangeMagnitude.EXTREME]
            ]
            if extreme_slots:
                extreme_changes_by_contract[address] = extreme_slots

        # 如果多个合约同时有极端变化,标记为潜在关联
        if len(extreme_changes_by_contract) >= 2:
            contract_list = list(extreme_changes_by_contract.keys())
            slot_list = []
            for addr in contract_list:
                slots = [sc.slot for sc in extreme_changes_by_contract[addr]]
                slot_list.extend(slots)

            relations.append(CrossContractRelation(
                relation_type="correlated_extreme_changes",
                contracts=contract_list,
                slots=slot_list,
                description=f"Multiple contracts with extreme storage changes (potential attack)",
                correlation_score=0.8
            ))

        self.logger.debug(f"检测到 {len(relations)} 个跨合约关系")
        return relations

    def get_summary(self, report: DiffReport) -> str:
        """生成差异报告摘要"""
        lines = [
            "=== State Diff Summary ===",
            f"Contracts changed: {report.total_contracts_changed}",
            f"Slots changed: {report.total_slots_changed}",
            f"Extreme changes: {len(report.extreme_changes)}",
            f"Cross-contract relations: {len(report.cross_contract_relations)}",
            "",
            "Top changes:"
        ]

        # 列出前5个最大变化
        all_changes = []
        for diff in report.contract_diffs.values():
            for sc in diff.slot_changes:
                all_changes.append((diff.address, sc))

        all_changes.sort(key=lambda x: x[1].change_rate, reverse=True)

        for i, (address, sc) in enumerate(all_changes[:5], 1):
            lines.append(
                f"  {i}. {address[:10]}... slot {sc.slot}: "
                f"{sc.direction.value} {sc.change_rate:.2%} ({sc.magnitude.value})"
            )

        return "\n".join(lines)
