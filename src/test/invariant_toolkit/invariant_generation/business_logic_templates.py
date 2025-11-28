"""
业务逻辑模板库

为不同DeFi协议类型提供业务逻辑不变量模板。
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from ..protocol_detection import ProtocolType

logger = logging.getLogger(__name__)


class InvariantCategory(Enum):
    """不变量类别"""
    RATIO_STABILITY = "ratio_stability"              # 比率稳定性
    MONOTONICITY = "monotonicity"                    # 单调性
    CONSERVATION = "conservation"                    # 守恒性
    BOUNDED_VALUE = "bounded_value"                  # 值范围限制
    STATE_CONSISTENCY = "state_consistency"          # 状态一致性
    BALANCE_CONSTRAINT = "balance_constraint"        # 余额约束


@dataclass
class InvariantTemplate:
    """不变量模板"""
    name: str
    category: InvariantCategory
    description: str
    formula_template: str  # 公式模板 (包含占位符)
    required_slots: List[str]  # 需要的槽位语义类型
    threshold: float  # 阈值
    severity: str = "medium"  # low, medium, high, critical


class BusinessLogicTemplates:
    """
    业务逻辑模板库

    为各种DeFi协议提供特定的业务逻辑不变量模板。
    """

    # Vault协议模板
    VAULT_TEMPLATES = [
        InvariantTemplate(
            name="share_price_stability",
            category=InvariantCategory.RATIO_STABILITY,
            description="Vault份额价格应保持稳定 (totalAssets / totalSupply)",
            formula_template=(
                "abs((vault.totalAssets / vault.totalSupply) - baseline) / baseline <= {threshold}"
            ),
            required_slots=["totalSupply", "totalAssets", "reserve"],
            threshold=0.05,  # 5%阈值
            severity="critical"
        ),
        InvariantTemplate(
            name="share_price_monotonic",
            category=InvariantCategory.MONOTONICITY,
            description="份额价格应单调非递减 (除非有费用收割)",
            formula_template=(
                "(totalAssets_after / totalSupply_after) >= (totalAssets_before / totalSupply_before) "
                "|| fee_harvest_event"
            ),
            required_slots=["totalSupply", "totalAssets"],
            threshold=0.0,
            severity="high"
        ),
        InvariantTemplate(
            name="total_assets_consistency",
            category=InvariantCategory.STATE_CONSISTENCY,
            description="Vault的totalAssets应等于底层资产余额",
            formula_template=(
                "abs(vault.totalAssets - underlying.balanceOf(vault)) / vault.totalAssets <= {threshold}"
            ),
            required_slots=["totalAssets", "balance_mapping"],
            threshold=0.01,  # 1%容差
            severity="high"
        ),
        InvariantTemplate(
            name="withdrawal_bounded",
            category=InvariantCategory.BOUNDED_VALUE,
            description="单次提款不应超过总资产的特定比例",
            formula_template=(
                "withdrawal_amount <= vault.totalAssets * {threshold}"
            ),
            required_slots=["totalAssets"],
            threshold=0.5,  # 50%
            severity="medium"
        ),
    ]

    # AMM协议模板
    AMM_TEMPLATES = [
        InvariantTemplate(
            name="constant_product",
            category=InvariantCategory.CONSERVATION,
            description="恒定乘积 k = reserve0 * reserve1 应在swap后保持或增加",
            formula_template=(
                "reserve0_after * reserve1_after >= reserve0_before * reserve1_before * (1 - {threshold})"
            ),
            required_slots=["reserve"],
            threshold=0.003,  # 0.3% (考虑手续费)
            severity="critical"
        ),
        InvariantTemplate(
            name="price_impact_bounded",
            category=InvariantCategory.BOUNDED_VALUE,
            description="单次交易价格影响应有上限",
            formula_template=(
                "abs((price_after - price_before) / price_before) <= {threshold}"
            ),
            required_slots=["reserve"],
            threshold=0.1,  # 10%
            severity="high"
        ),
        InvariantTemplate(
            name="reserve_non_zero",
            category=InvariantCategory.STATE_CONSISTENCY,
            description="储备量不应为零",
            formula_template=(
                "reserve0 > 0 && reserve1 > 0"
            ),
            required_slots=["reserve"],
            threshold=0.0,
            severity="critical"
        ),
        InvariantTemplate(
            name="total_supply_consistency",
            category=InvariantCategory.STATE_CONSISTENCY,
            description="LP代币总量应与储备量一致",
            formula_template=(
                "totalSupply == sqrt(reserve0 * reserve1) - MINIMUM_LIQUIDITY"
            ),
            required_slots=["totalSupply", "reserve"],
            threshold=0.01,
            severity="medium"
        ),
    ]

    # Lending协议模板
    LENDING_TEMPLATES = [
        InvariantTemplate(
            name="collateralization_ratio",
            category=InvariantCategory.RATIO_STABILITY,
            description="抵押率应维持在安全水平以上",
            formula_template=(
                "collateral_value / borrow_value >= {threshold}"
            ),
            required_slots=["collateral", "debt"],
            threshold=1.5,  # 150%
            severity="critical"
        ),
        InvariantTemplate(
            name="utilization_bounded",
            category=InvariantCategory.BOUNDED_VALUE,
            description="资金利用率应有上限",
            formula_template=(
                "total_borrows / (total_borrows + total_cash) <= {threshold}"
            ),
            required_slots=["debt", "reserve"],
            threshold=0.95,  # 95%
            severity="high"
        ),
        InvariantTemplate(
            name="borrow_balance_accuracy",
            category=InvariantCategory.STATE_CONSISTENCY,
            description="借款余额应等于本金加利息",
            formula_template=(
                "abs(borrow_balance - (principal + accrued_interest)) / borrow_balance <= {threshold}"
            ),
            required_slots=["debt"],
            threshold=0.01,
            severity="medium"
        ),
        InvariantTemplate(
            name="liquidation_threshold",
            category=InvariantCategory.BOUNDED_VALUE,
            description="健康因子低于阈值时应触发清算",
            formula_template=(
                "health_factor < {threshold} => can_liquidate"
            ),
            required_slots=["collateral", "debt"],
            threshold=1.0,
            severity="high"
        ),
    ]

    # Staking协议模板
    STAKING_TEMPLATES = [
        InvariantTemplate(
            name="reward_per_token_monotonic",
            category=InvariantCategory.MONOTONICITY,
            description="每代币奖励应单调递增",
            formula_template=(
                "reward_per_token_after >= reward_per_token_before"
            ),
            required_slots=["reward_per_token"],
            threshold=0.0,
            severity="high"
        ),
        InvariantTemplate(
            name="staked_balance_consistency",
            category=InvariantCategory.STATE_CONSISTENCY,
            description="质押总量应等于所有用户质押之和",
            formula_template=(
                "abs(total_staked - sum(user_balances)) / total_staked <= {threshold}"
            ),
            required_slots=["totalSupply", "balance_mapping"],
            threshold=0.01,
            severity="medium"
        ),
        InvariantTemplate(
            name="reward_rate_bounded",
            category=InvariantCategory.BOUNDED_VALUE,
            description="奖励速率应有合理上限",
            formula_template=(
                "reward_rate <= {threshold}"
            ),
            required_slots=["reward_amount"],
            threshold=1e24,  # 具体值需根据代币精度调整
            severity="low"
        ),
    ]

    # ERC20基础模板
    ERC20_TEMPLATES = [
        InvariantTemplate(
            name="total_supply_conservation",
            category=InvariantCategory.CONSERVATION,
            description="非铸造/销毁情况下总供应量守恒",
            formula_template=(
                "totalSupply_after == totalSupply_before || mint_event || burn_event"
            ),
            required_slots=["totalSupply"],
            threshold=0.0,
            severity="high"
        ),
        InvariantTemplate(
            name="balance_sum_equals_supply",
            category=InvariantCategory.STATE_CONSISTENCY,
            description="所有余额之和应等于总供应量",
            formula_template=(
                "sum(balances) == totalSupply"
            ),
            required_slots=["totalSupply", "balance_mapping"],
            threshold=0.0,
            severity="medium"
        ),
    ]

    @classmethod
    def get_templates_for_protocol(cls, protocol_type: ProtocolType) -> List[InvariantTemplate]:
        """
        获取特定协议类型的模板

        Args:
            protocol_type: 协议类型

        Returns:
            适用的不变量模板列表
        """
        template_map = {
            ProtocolType.VAULT: cls.VAULT_TEMPLATES,
            ProtocolType.AMM: cls.AMM_TEMPLATES,
            ProtocolType.LENDING: cls.LENDING_TEMPLATES,
            ProtocolType.STAKING: cls.STAKING_TEMPLATES,
            ProtocolType.ERC20: cls.ERC20_TEMPLATES,
        }

        templates = template_map.get(protocol_type, [])

        # 所有协议都应用ERC20基础模板 (如果实现了ERC20)
        if protocol_type != ProtocolType.ERC20:
            templates = templates + cls.ERC20_TEMPLATES

        return templates

    @classmethod
    def get_all_templates(cls) -> Dict[str, List[InvariantTemplate]]:
        """获取所有模板,按协议类型分组"""
        return {
            "vault": cls.VAULT_TEMPLATES,
            "amm": cls.AMM_TEMPLATES,
            "lending": cls.LENDING_TEMPLATES,
            "staking": cls.STAKING_TEMPLATES,
            "erc20": cls.ERC20_TEMPLATES,
        }

    @classmethod
    def get_template_by_name(cls, name: str) -> Optional[InvariantTemplate]:
        """根据名称查找模板"""
        all_templates = cls.get_all_templates()

        for protocol_templates in all_templates.values():
            for template in protocol_templates:
                if template.name == name:
                    return template

        return None
