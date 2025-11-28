"""
变化模式检测器

识别攻击特征模式,如闪电贷极端变化、价格操纵单调性、重入递归调用等。
"""

import logging
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from .diff_calculator import DiffReport, SlotChange, ChangeMagnitude, ChangeDirection

logger = logging.getLogger(__name__)


class PatternType(Enum):
    """模式类型"""
    # 闪电贷特征
    FLASH_CHANGE = "flash_change"                    # 极端变化后恢复
    FLASH_MINT = "flash_mint"                        # 大量铸币后销毁

    # 价格操纵
    PRICE_MANIPULATION = "price_manipulation"         # 价格异常波动
    RATIO_BREAK = "ratio_break"                      # 比率关系破坏
    MONOTONIC_INCREASE = "monotonic_increase"         # 单调递增(异常)

    # 重入攻击
    RECURSIVE_CALL = "recursive_call"                # 递归调用深度异常
    REENTRANCY_BALANCE = "reentrancy_balance"        # 重入导致的余额异常

    # 权限异常
    OWNERSHIP_CHANGE = "ownership_change"            # 所有权变更
    UNAUTHORIZED_MINT = "unauthorized_mint"          # 未授权铸币

    # 其他异常
    MASSIVE_TRANSFER = "massive_transfer"            # 巨额转账
    ABNORMAL_NONCE = "abnormal_nonce"                # 异常nonce增长
    ZERO_VALUE_CHANGE = "zero_value_change"          # 从0突变


@dataclass
class ChangePattern:
    """检测到的变化模式"""
    pattern_type: PatternType
    description: str
    confidence: float  # 0-1
    evidence: List[str] = field(default_factory=list)

    # 涉及的合约和槽位
    contracts: List[str] = field(default_factory=list)
    slots: List[str] = field(default_factory=list)

    # 严重性评级
    severity: str = "medium"  # low, medium, high, critical


class ChangePatternDetector:
    """
    变化模式检测器

    分析DiffReport识别攻击特征模式。
    """

    # 阈值配置
    THRESHOLDS = {
        "flash_change_rate": 10.0,           # 1000%变化视为闪电贷
        "massive_transfer_ratio": 0.5,       # 超过总供应量50%视为巨额
        "abnormal_nonce_increment": 10,      # nonce一次增长超过10视为异常
        "zero_change_min": 1e18,             # 从0变化超过1e18视为异常
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.ChangePatternDetector')

    def detect_patterns(self, diff_report: DiffReport) -> List[ChangePattern]:
        """
        检测所有模式

        Args:
            diff_report: 状态差异报告

        Returns:
            检测到的模式列表
        """
        self.logger.info("开始检测变化模式...")

        patterns = []

        # 1. 检测闪电贷模式
        patterns.extend(self._detect_flash_patterns(diff_report))

        # 2. 检测价格操纵模式
        patterns.extend(self._detect_price_manipulation(diff_report))

        # 3. 检测重入模式
        patterns.extend(self._detect_reentrancy_patterns(diff_report))

        # 4. 检测权限异常
        patterns.extend(self._detect_permission_anomalies(diff_report))

        # 5. 检测其他异常
        patterns.extend(self._detect_other_anomalies(diff_report))

        self.logger.info(f"检测完成: 发现 {len(patterns)} 个模式")

        return patterns

    def _detect_flash_patterns(self, report: DiffReport) -> List[ChangePattern]:
        """检测闪电贷相关模式"""
        patterns = []

        # 检查极端变化
        for contract_addr, diff in report.contract_diffs.items():
            extreme_slots = [
                sc for sc in diff.slot_changes
                if sc.magnitude == ChangeMagnitude.EXTREME
            ]

            if extreme_slots:
                # 闪电贷通常表现为极端的增加
                flash_evidence = []
                for sc in extreme_slots:
                    if sc.change_rate > self.THRESHOLDS["flash_change_rate"]:
                        flash_evidence.append(
                            f"Slot {sc.slot}: {sc.change_rate:.0f}x change"
                        )

                if flash_evidence:
                    patterns.append(ChangePattern(
                        pattern_type=PatternType.FLASH_CHANGE,
                        description=f"Extreme value changes indicating potential flash loan attack",
                        confidence=0.9,
                        evidence=flash_evidence,
                        contracts=[contract_addr],
                        slots=[sc.slot for sc in extreme_slots],
                        severity="critical"
                    ))

        return patterns

    def _detect_price_manipulation(self, report: DiffReport) -> List[ChangePattern]:
        """检测价格操纵模式"""
        patterns = []

        # 检测比率破坏
        # 例如: Vault的 totalSupply vs underlying balance 比率异常变化
        for relation in report.cross_contract_relations:
            if relation.relation_type == "correlated_extreme_changes":
                patterns.append(ChangePattern(
                    pattern_type=PatternType.RATIO_BREAK,
                    description="Correlated extreme changes across contracts (potential ratio manipulation)",
                    confidence=0.8,
                    evidence=[relation.description],
                    contracts=relation.contracts,
                    slots=relation.slots,
                    severity="high"
                ))

        # 检测单调递增异常 (价格只增不减可能是操纵)
        for contract_addr, diff in report.contract_diffs.items():
            large_increases = [
                sc for sc in diff.slot_changes
                if sc.direction == ChangeDirection.INCREASE
                and sc.magnitude in [ChangeMagnitude.LARGE, ChangeMagnitude.MASSIVE, ChangeMagnitude.EXTREME]
            ]

            # 如果有多个槽位都是大幅增加,可能是价格操纵
            if len(large_increases) >= 2:
                patterns.append(ChangePattern(
                    pattern_type=PatternType.MONOTONIC_INCREASE,
                    description=f"Multiple slots with large increases (potential price manipulation)",
                    confidence=0.7,
                    evidence=[f"Slot {sc.slot}: +{sc.change_rate:.2%}" for sc in large_increases],
                    contracts=[contract_addr],
                    slots=[sc.slot for sc in large_increases],
                    severity="high"
                ))

        return patterns

    def _detect_reentrancy_patterns(self, report: DiffReport) -> List[ChangePattern]:
        """检测重入攻击模式"""
        patterns = []

        # 重入攻击的特征:
        # 1. 余额异常减少 (未经授权的多次提取)
        # 2. Nonce异常增长 (多次重入调用)

        for contract_addr, diff in report.contract_diffs.items():
            # 检查nonce异常增长
            if diff.nonce_change > self.THRESHOLDS["abnormal_nonce_increment"]:
                patterns.append(ChangePattern(
                    pattern_type=PatternType.RECURSIVE_CALL,
                    description=f"Abnormal nonce increment: +{diff.nonce_change}",
                    confidence=0.85,
                    evidence=[f"Nonce changed from X to X+{diff.nonce_change}"],
                    contracts=[contract_addr],
                    severity="high"
                ))

            # 检查余额异常减少
            if diff.balance_change < 0:
                # 大幅余额减少
                if abs(diff.balance_change) > 10 ** 18:  # > 1 ETH
                    patterns.append(ChangePattern(
                        pattern_type=PatternType.REENTRANCY_BALANCE,
                        description=f"Large balance decrease: {abs(diff.balance_change) / 1e18:.2f} ETH",
                        confidence=0.75,
                        evidence=[f"Balance decreased by {abs(diff.balance_change)} wei"],
                        contracts=[contract_addr],
                        severity="high"
                    ))

        return patterns

    def _detect_permission_anomalies(self, report: DiffReport) -> List[ChangePattern]:
        """检测权限异常"""
        patterns = []

        # 检测所有权变更 (通常在slot 0或有"owner"语义的槽位)
        for contract_addr, diff in report.contract_diffs.items():
            for sc in diff.slot_changes:
                # 检查slot 0变化 (通常是owner)
                if sc.slot in ["0", "0x0"]:
                    if sc.semantic_type and "owner" in sc.semantic_type.lower():
                        patterns.append(ChangePattern(
                            pattern_type=PatternType.OWNERSHIP_CHANGE,
                            description=f"Ownership change detected in contract {contract_addr[:10]}...",
                            confidence=0.9,
                            evidence=[f"Slot {sc.slot} (owner) changed from {sc.value_before} to {sc.value_after}"],
                            contracts=[contract_addr],
                            slots=[sc.slot],
                            severity="critical"
                        ))

        return patterns

    def _detect_other_anomalies(self, report: DiffReport) -> List[ChangePattern]:
        """检测其他异常模式"""
        patterns = []

        # 检测从0突变
        for contract_addr, diff in report.contract_diffs.items():
            for sc in diff.slot_changes:
                if sc.value_before and int(sc.value_before, 16) == 0:
                    value_after = int(sc.value_after, 16) if sc.value_after else 0
                    if value_after > self.THRESHOLDS["zero_change_min"]:
                        patterns.append(ChangePattern(
                            pattern_type=PatternType.ZERO_VALUE_CHANGE,
                            description=f"Value changed from 0 to {value_after}",
                            confidence=0.6,
                            evidence=[f"Slot {sc.slot}: 0 -> {value_after}"],
                            contracts=[contract_addr],
                            slots=[sc.slot],
                            severity="medium"
                        ))

        # 检测巨额转账
        for relation in report.cross_contract_relations:
            if relation.relation_type == "balance_transfer":
                # 从描述中提取金额 (简化处理)
                if "wei" in relation.description:
                    patterns.append(ChangePattern(
                        pattern_type=PatternType.MASSIVE_TRANSFER,
                        description=relation.description,
                        confidence=0.8,
                        evidence=[relation.description],
                        contracts=relation.contracts,
                        severity="medium"
                    ))

        return patterns

    def get_summary(self, patterns: List[ChangePattern]) -> str:
        """生成模式检测摘要"""
        lines = [
            "=== Pattern Detection Summary ===",
            f"Total patterns detected: {len(patterns)}",
            ""
        ]

        # 按严重性分组
        by_severity = {"critical": [], "high": [], "medium": [], "low": []}
        for p in patterns:
            by_severity[p.severity].append(p)

        for severity in ["critical", "high", "medium", "low"]:
            count = len(by_severity[severity])
            if count > 0:
                lines.append(f"{severity.upper()}: {count} patterns")
                for p in by_severity[severity][:3]:  # 显示前3个
                    lines.append(f"  - {p.pattern_type.value}: {p.description}")

        return "\n".join(lines)
