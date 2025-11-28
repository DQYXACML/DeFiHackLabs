"""
事件分类器

基于合约ABI的事件签名分析,辅助识别DeFi协议类型。
"""

import logging
from typing import Dict, List, Set
from dataclasses import dataclass
from .abi_analyzer import ProtocolType

logger = logging.getLogger(__name__)


@dataclass
class EventPattern:
    """事件模式"""
    protocol_type: ProtocolType
    event_names: List[str]
    weight: float  # 匹配权重


class EventClassifier:
    """
    事件分类器

    通过分析合约ABI中的事件名称和参数,
    辅助识别协议类型。
    """

    # 协议特征事件库
    EVENT_PATTERNS = {
        ProtocolType.VAULT: [
            EventPattern(ProtocolType.VAULT, ["Deposit", "Withdraw", "SharesMinted", "SharesBurned"], weight=0.3),
            EventPattern(ProtocolType.VAULT, ["Harvest", "StrategyReported", "StrategyAdded"], weight=0.2),
        ],

        ProtocolType.AMM: [
            EventPattern(ProtocolType.AMM, ["Swap", "Sync", "Mint", "Burn"], weight=0.4),
            EventPattern(ProtocolType.AMM, ["PairCreated", "Swap", "AddLiquidity", "RemoveLiquidity"], weight=0.3),
        ],

        ProtocolType.LENDING: [
            EventPattern(ProtocolType.LENDING, ["Borrow", "Repay", "Liquidate", "LiquidationCall"], weight=0.4),
            EventPattern(ProtocolType.LENDING, ["Supply", "Redeem", "ReserveUpdated"], weight=0.2),
        ],

        ProtocolType.STAKING: [
            EventPattern(ProtocolType.STAKING, ["Staked", "Unstaked", "RewardPaid", "RewardAdded"], weight=0.4),
            EventPattern(ProtocolType.STAKING, ["Claimed", "Compounded"], weight=0.2),
        ],

        ProtocolType.BRIDGE: [
            EventPattern(ProtocolType.BRIDGE, ["MessageSent", "MessageReceived", "RelayMessage"], weight=0.3),
            EventPattern(ProtocolType.BRIDGE, ["Locked", "Unlocked", "BridgeInitiated"], weight=0.3),
        ],

        ProtocolType.NFT_MARKETPLACE: [
            EventPattern(ProtocolType.NFT_MARKETPLACE, ["ItemListed", "ItemSold", "ItemCanceled"], weight=0.3),
            EventPattern(ProtocolType.NFT_MARKETPLACE, ["OfferMade", "OfferAccepted"], weight=0.2),
        ],

        ProtocolType.GOVERNANCE: [
            EventPattern(ProtocolType.GOVERNANCE, ["ProposalCreated", "VoteCast", "ProposalExecuted"], weight=0.4),
            EventPattern(ProtocolType.GOVERNANCE, ["ProposalQueued", "ProposalCanceled"], weight=0.2),
        ],

        ProtocolType.ERC20: [
            EventPattern(ProtocolType.ERC20, ["Transfer", "Approval"], weight=0.5),
            EventPattern(ProtocolType.ERC20, ["Mint", "Burn"], weight=0.1),
        ],
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.EventClassifier')

    def classify_by_events(self, abi: List[Dict]) -> Dict:
        """
        基于事件类型推断协议

        Args:
            abi: 合约ABI (JSON格式)

        Returns:
            {
                "protocol_scores": {"vault": 0.6, "amm": 0.2, ...},
                "detected_type": ProtocolType.VAULT,
                "confidence": 0.6,
                "matched_events": {...},
                "evidence": [...]
            }
        """
        # 1. 提取事件名称
        event_names = self._extract_events(abi)

        # 2. 计算每种协议类型的匹配分数
        protocol_scores = {}
        matched_events = {}
        evidence = []

        for protocol_type, patterns in self.EVENT_PATTERNS.items():
            score, matches = self._calculate_protocol_score(event_names, patterns)
            protocol_scores[protocol_type.value] = score
            matched_events[protocol_type.value] = matches

            if score > 0:
                evidence.append(f"{protocol_type.value}: 匹配 {len(matches)} 个事件 (score={score:.2f})")

        # 3. 确定最佳匹配
        best_protocol = max(protocol_scores.items(), key=lambda x: x[1])
        detected_type = ProtocolType(best_protocol[0]) if best_protocol[1] > 0 else ProtocolType.UNKNOWN
        confidence = best_protocol[1]

        self.logger.info(f"事件分类结果: {detected_type.value} (confidence={confidence:.2f})")

        return {
            "protocol_scores": protocol_scores,
            "detected_type": detected_type,
            "confidence": confidence,
            "matched_events": matched_events,
            "evidence": evidence,
            "total_events": len(event_names)
        }

    def _extract_events(self, abi: List[Dict]) -> Set[str]:
        """从ABI提取事件名称"""
        events = set()

        for item in abi:
            if item.get("type") == "event":
                event_name = item.get("name", "")
                if event_name:
                    events.add(event_name)

        self.logger.debug(f"提取到 {len(events)} 个事件")
        return events

    def _calculate_protocol_score(
        self,
        event_names: Set[str],
        patterns: List[EventPattern]
    ) -> tuple[float, List[str]]:
        """
        计算协议匹配分数

        评分规则:
        - 匹配的事件名称数量 * 模式权重
        - 标准化到[0, 1]

        Returns:
            (score, matched_event_names)
        """
        matched = []
        score = 0.0

        for pattern in patterns:
            pattern_matches = event_names.intersection(set(pattern.event_names))
            if pattern_matches:
                # 匹配的事件数量 * 权重
                match_ratio = len(pattern_matches) / len(pattern.event_names)
                score += match_ratio * pattern.weight
                matched.extend(pattern_matches)

        # 标准化分数到[0, 1]
        score = min(score, 1.0)

        return score, matched

    def get_critical_events(self, abi: List[Dict]) -> Dict[str, List[str]]:
        """
        识别关键事件

        返回:
            {
                "value_transfer": [...],  # 涉及资产转移的事件
                "state_change": [...],    # 状态变更事件
                "governance": [...]       # 治理相关事件
            }
        """
        critical = {
            "value_transfer": [],
            "state_change": [],
            "governance": []
        }

        value_keywords = ["transfer", "deposit", "withdraw", "mint", "burn", "swap", "borrow", "repay"]
        state_keywords = ["update", "change", "set", "sync", "harvest", "rebalance"]
        governance_keywords = ["proposal", "vote", "execute", "queue", "cancel"]

        for item in abi:
            if item.get("type") != "event":
                continue

            name = item.get("name", "").lower()

            # 检查资产转移
            if any(kw in name for kw in value_keywords):
                critical["value_transfer"].append(item["name"])

            # 检查状态变更
            if any(kw in name for kw in state_keywords):
                critical["state_change"].append(item["name"])

            # 检查治理相关
            if any(kw in name for kw in governance_keywords):
                critical["governance"].append(item["name"])

        return critical
