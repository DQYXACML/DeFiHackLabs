"""
Slot语义类型定义和映射器

定义存储槽位的语义类型,并提供基于变量名的模式匹配映射功能。
"""

import re
import logging
from enum import Enum
from typing import Dict, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class SlotSemanticType(Enum):
    """存储槽位语义类型枚举"""
    # ERC20相关
    TOTAL_SUPPLY = "totalSupply"
    BALANCE_MAPPING = "balance_mapping"
    ALLOWANCE_MAPPING = "allowance_mapping"

    # DeFi协议相关
    RESERVE = "reserve"
    DEBT = "debt"
    COLLATERAL = "collateral"
    SHARE_PRICE = "share_price"

    # 价格和预言机
    PRICE_ORACLE = "price_oracle"
    PRICE_FEED = "price_feed"
    CUMULATIVE_PRICE = "cumulative_price"

    # 治理和权限
    OWNER = "owner"
    ADMIN = "admin"
    PAUSED = "paused"
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"

    # 时间相关
    TIMESTAMP = "timestamp"
    LAST_UPDATE = "last_update"
    DEADLINE = "deadline"

    # 金额和数量
    TOKEN_AMOUNT = "token_amount"
    REWARD_AMOUNT = "reward_amount"
    FEE_AMOUNT = "fee_amount"

    # 引用和地址
    ADDRESS_REFERENCE = "address_reference"
    TOKEN_ADDRESS = "token_address"
    PAIR_ADDRESS = "pair_address"

    # 其他
    NONCE = "nonce"
    COUNTER = "counter"
    FLAG = "flag"
    UNKNOWN = "unknown"


@dataclass
class SemanticPattern:
    """语义模式定义"""
    semantic_type: SlotSemanticType
    patterns: List[str]  # 正则表达式列表
    priority: int = 1  # 优先级,数字越大优先级越高

    def matches(self, variable_name: str) -> bool:
        """检查变量名是否匹配模式"""
        name_lower = variable_name.lower()
        for pattern in self.patterns:
            if re.search(pattern, name_lower, re.IGNORECASE):
                return True
        return False


class SlotSemanticMapper:
    """
    槽位语义映射器

    基于变量名模式匹配,将状态变量映射到语义类型。
    """

    # 语义模式库 (按优先级降序排列)
    SEMANTIC_PATTERNS = [
        # 优先级5: 精确匹配
        SemanticPattern(SlotSemanticType.TOTAL_SUPPLY, [r'^_?totalSupply$', r'^total_supply$'], priority=5),
        SemanticPattern(SlotSemanticType.OWNER, [r'^_?owner$', r'^_owner$'], priority=5),
        SemanticPattern(SlotSemanticType.PAUSED, [r'^_?paused$'], priority=5),

        # 优先级4: ERC20标准
        SemanticPattern(SlotSemanticType.BALANCE_MAPPING, [r'^_?balances?$', r'^_balanceOf$', r'balanceOf'], priority=4),
        SemanticPattern(SlotSemanticType.ALLOWANCE_MAPPING, [r'^_?allowances?$', r'_allowance'], priority=4),

        # 优先级3: 协议核心变量
        SemanticPattern(SlotSemanticType.RESERVE, [
            r'reserve[0-9]*$',
            r'_reserve',
            r'totalReserve',
            r'liquidityReserve'
        ], priority=3),

        SemanticPattern(SlotSemanticType.DEBT, [
            r'debt',
            r'borrowed',
            r'totalBorrow',
            r'outstandingDebt'
        ], priority=3),

        SemanticPattern(SlotSemanticType.COLLATERAL, [
            r'collateral',
            r'locked',
            r'staked'
        ], priority=3),

        # 优先级2: 价格相关
        SemanticPattern(SlotSemanticType.PRICE_ORACLE, [
            r'oracle',
            r'priceFeed',
            r'priceSource'
        ], priority=2),

        SemanticPattern(SlotSemanticType.CUMULATIVE_PRICE, [
            r'cumulativePrice',
            r'priceAccumulator',
            r'price.*Cumulative'
        ], priority=2),

        # 优先级1: 通用模式
        SemanticPattern(SlotSemanticType.TIMESTAMP, [
            r'timestamp',
            r'lastUpdate',
            r'updatedAt',
            r'.*Time$'
        ], priority=1),

        SemanticPattern(SlotSemanticType.ADDRESS_REFERENCE, [
            r'.*Address$',
            r'token[0-9]',
            r'underlying',
            r'target'
        ], priority=1),

        SemanticPattern(SlotSemanticType.NONCE, [
            r'nonce',
            r'sequenceNumber'
        ], priority=1),

        SemanticPattern(SlotSemanticType.FEE_AMOUNT, [
            r'fee',
            r'.*Fee$',
            r'commission'
        ], priority=1),

        SemanticPattern(SlotSemanticType.REWARD_AMOUNT, [
            r'reward',
            r'yield',
            r'interest'
        ], priority=1),
    ]

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.SlotSemanticMapper')
        # 按优先级排序模式
        self.patterns = sorted(self.SEMANTIC_PATTERNS, key=lambda p: p.priority, reverse=True)

    def map_variable_to_semantic(
        self,
        variable_name: str,
        variable_type: str = None,
        value: str = None
    ) -> Dict:
        """
        将变量名映射到语义类型

        Args:
            variable_name: 变量名
            variable_type: 变量类型 (如 "uint256", "mapping(address => uint256)")
            value: 变量值 (可选,用于辅助判断)

        Returns:
            {
                "semantic_type": SlotSemanticType,
                "confidence": float,
                "reason": str
            }
        """
        # 1. 基于变量名模式匹配
        for pattern in self.patterns:
            if pattern.matches(variable_name):
                confidence = self._calculate_confidence(pattern, variable_type, value)
                return {
                    "semantic_type": pattern.semantic_type,
                    "confidence": confidence,
                    "reason": f"Pattern match: {pattern.patterns[0]} (priority={pattern.priority})"
                }

        # 2. 基于类型推断
        if variable_type:
            type_based = self._infer_from_type(variable_type)
            if type_based:
                return type_based

        # 3. 基于值推断
        if value:
            value_based = self._infer_from_value(value)
            if value_based:
                return value_based

        # 4. 默认为UNKNOWN
        return {
            "semantic_type": SlotSemanticType.UNKNOWN,
            "confidence": 0.1,
            "reason": "No pattern matched"
        }

    def _calculate_confidence(
        self,
        pattern: SemanticPattern,
        variable_type: Optional[str],
        value: Optional[str]
    ) -> float:
        """计算匹配置信度"""
        base_confidence = 0.5 + (pattern.priority * 0.1)

        # 类型匹配加成
        if variable_type:
            if pattern.semantic_type == SlotSemanticType.BALANCE_MAPPING and "mapping" in variable_type:
                base_confidence += 0.2
            elif pattern.semantic_type == SlotSemanticType.TOTAL_SUPPLY and "uint" in variable_type:
                base_confidence += 0.1

        # 确保在[0, 1]范围内
        return min(base_confidence, 1.0)

    def _infer_from_type(self, variable_type: str) -> Optional[Dict]:
        """基于变量类型推断语义"""
        type_lower = variable_type.lower()

        # Mapping类型通常是余额或授权
        if "mapping(address" in type_lower:
            if "uint" in type_lower:
                return {
                    "semantic_type": SlotSemanticType.BALANCE_MAPPING,
                    "confidence": 0.6,
                    "reason": "Type inference: mapping(address => uint256)"
                }
            elif "mapping" in type_lower:  # 嵌套mapping可能是授权
                return {
                    "semantic_type": SlotSemanticType.ALLOWANCE_MAPPING,
                    "confidence": 0.5,
                    "reason": "Type inference: nested mapping"
                }

        return None

    def _infer_from_value(self, value: str) -> Optional[Dict]:
        """基于值推断语义"""
        try:
            value_int = int(value, 16) if value.startswith('0x') else int(value)
        except (ValueError, TypeError):
            return None

        # 地址范围 (0 < value < 2^160)
        if 0 < value_int < 2**160:
            return {
                "semantic_type": SlotSemanticType.ADDRESS_REFERENCE,
                "confidence": 0.7,
                "reason": f"Value in address range: {value}"
            }

        # Token数量范围 (10^18 - 10^27)
        if 10**18 <= value_int <= 10**27:
            return {
                "semantic_type": SlotSemanticType.TOKEN_AMOUNT,
                "confidence": 0.5,
                "reason": "Value in token amount range (1e18-1e27)"
            }

        # 时间戳范围 (接近当前Unix时间)
        if 1600000000 <= value_int <= 2000000000:  # 2020-2033
            return {
                "semantic_type": SlotSemanticType.TIMESTAMP,
                "confidence": 0.6,
                "reason": "Value in timestamp range"
            }

        return None

    def batch_map_variables(
        self,
        variables: List[Dict]
    ) -> Dict[str, Dict]:
        """
        批量映射变量

        Args:
            variables: [{"name": "totalSupply", "type": "uint256", "value": "0x..."}]

        Returns:
            {
                "totalSupply": {"semantic_type": ..., "confidence": ..., ...},
                ...
            }
        """
        results = {}
        for var in variables:
            name = var.get("name", "")
            var_type = var.get("type")
            value = var.get("value")

            results[name] = self.map_variable_to_semantic(name, var_type, value)

        return results
