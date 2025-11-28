#!/usr/bin/env python3
"""
改进的阈值计算模块

基于攻击类型和协议特征动态计算不变量阈值，提升规则准确性。

主要功能：
1. 自动检测攻击类型（闪电贷、重入、价格操纵等）
2. 基于攻击类型使用不同的阈值系数
3. 根据协议类型（AMM、Vault、Lending）调整阈值
4. 提供可追溯的计算过程（记录在metadata中）

使用示例：
    calculator = ImprovedThresholdCalculator()

    # 检测攻击类型
    attack_type = calculator.detect_attack_type(monitor_data)

    # 计算阈值
    threshold = calculator.calculate_adaptive_threshold(
        metric_name='loop',
        observed_value=25,
        attack_type=attack_type,
        protocol_type='amm'
    )

作者: Claude Code
版本: 1.0.0
"""

from enum import Enum
from typing import Dict, Any, Optional
import logging

# ============================================================================
# 枚举定义
# ============================================================================

class AttackType(Enum):
    """攻击类型分类"""
    FLASHLOAN = "flashloan"                      # 闪电贷攻击
    REENTRANCY = "reentrancy"                    # 重入攻击
    PRICE_MANIPULATION = "price_manipulation"    # 价格操纵
    ACCESS_CONTROL = "access_control"            # 访问控制漏洞
    LOGIC_ERROR = "logic_error"                  # 业务逻辑错误
    UNKNOWN = "unknown"                          # 未知类型


# ============================================================================
# 主类：改进的阈值计算器
# ============================================================================

class ImprovedThresholdCalculator:
    """
    改进的阈值计算器

    核心思想：不同类型的攻击应该有不同的阈值系数。
    - 闪电贷攻击：余额变化巨大，阈值要严格（系数0.1）
    - 重入攻击：调用深度异常，调用深度阈值要严格（系数0.3）
    - 价格操纵：循环和余额都异常，都要严格
    """

    # 基于攻击类型的系数配置
    # 系数越小 = 阈值越严格 = 越容易拦截
    ATTACK_TYPE_COEFFICIENTS = {
        AttackType.FLASHLOAN: {
            'loop': 0.3,         # 闪电贷通常循环较少
            'call_depth': 0.4,   # 调用深度中等
            'balance': 0.1,      # 余额变化巨大，阈值要非常严格
        },
        AttackType.REENTRANCY: {
            'loop': 0.4,
            'call_depth': 0.3,   # 重入导致调用深度大，阈值要严格
            'balance': 0.5,
        },
        AttackType.PRICE_MANIPULATION: {
            'loop': 0.4,         # 价格操纵通常需要多次swap
            'call_depth': 0.6,
            'balance': 0.2,      # 余额变化明显
        },
        AttackType.ACCESS_CONTROL: {
            'loop': 0.6,
            'call_depth': 0.6,
            'balance': 0.4,
        },
        AttackType.LOGIC_ERROR: {
            'loop': 0.5,
            'call_depth': 0.5,
            'balance': 0.5,
        },
        AttackType.UNKNOWN: {
            'loop': 0.5,         # 默认保守值
            'call_depth': 0.5,
            'balance': 0.5,
        }
    }

    # 协议类型修正系数
    # 用于调整不同协议的正常行为差异
    PROTOCOL_TYPE_MODIFIERS = {
        'vault': {
            'balance': 0.8,      # Vault的余额变化通常较小
            'loop': 1.0,
            'call_depth': 1.0,
        },
        'amm': {
            'balance': 1.2,      # AMM正常交易余额变化较大
            'loop': 0.9,         # AMM通常循环较少
            'call_depth': 1.1,
        },
        'lending': {
            'balance': 1.0,
            'loop': 1.0,
            'call_depth': 1.2,   # 借贷协议调用链较长
        },
        'staking': {
            'balance': 1.0,
            'loop': 1.0,
            'call_depth': 1.0,
        },
        'unknown': {
            'balance': 1.0,
            'loop': 1.0,
            'call_depth': 1.0,
        }
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.ImprovedThresholdCalculator')

    def detect_attack_type(self, monitor_data: Dict[str, Any]) -> AttackType:
        """
        基于Monitor数据自动检测攻击类型

        检测逻辑：
        1. 重入深度 > 0 → REENTRANCY
        2. 余额变化率 > 10% → FLASHLOAN
        3. 循环次数 > 10 或 调用深度 > 15 → PRICE_MANIPULATION
        4. 否则 → UNKNOWN

        Args:
            monitor_data: Monitor输出的完整数据

        Returns:
            检测到的攻击类型
        """
        tx_data = monitor_data.get('transaction_data', {})

        # 提取关键指标
        reentrancy_depth = tx_data.get('reentrancy_depth', 0)
        loop_iterations = tx_data.get('loop_iterations', 0)
        call_depth = tx_data.get('call_depth', 0)
        balance_changes = tx_data.get('balance_changes', {})

        # 1. 检测重入攻击（最高优先级）
        if reentrancy_depth > 0:
            self.logger.info(
                f"✓ 检测到重入攻击 (reentrancy_depth={reentrancy_depth})"
            )
            return AttackType.REENTRANCY

        # 2. 检测闪电贷攻击（基于余额变化）
        if balance_changes:
            max_change_rate = max(
                abs(change.get('change_rate', 0))
                for change in balance_changes.values()
            )

            # 单笔交易余额变化超过10%通常是闪电贷
            if max_change_rate > 0.1:
                self.logger.info(
                    f"✓ 检测到闪电贷攻击 (max_balance_change={max_change_rate:.2%})"
                )
                return AttackType.FLASHLOAN

        # 3. 检测价格操纵（基于循环和调用深度）
        if loop_iterations > 10 or call_depth > 15:
            self.logger.info(
                f"✓ 检测到价格操纵攻击 (loops={loop_iterations}, depth={call_depth})"
            )
            return AttackType.PRICE_MANIPULATION

        # 4. 默认：未知类型
        self.logger.warning(
            f"无法明确分类攻击类型 (loops={loop_iterations}, "
            f"depth={call_depth}, reentrancy={reentrancy_depth})"
        )
        return AttackType.UNKNOWN

    def calculate_adaptive_threshold(
        self,
        metric_name: str,
        observed_value: float,
        attack_type: AttackType,
        protocol_type: str = 'unknown'
    ) -> float:
        """
        计算自适应阈值

        计算公式：
            threshold = observed_value × attack_coefficient × protocol_modifier

        Args:
            metric_name: 指标名称 ('loop', 'call_depth', 'balance')
            observed_value: 攻击交易中观察到的值
            attack_type: 攻击类型
            protocol_type: 协议类型

        Returns:
            计算出的阈值

        Example:
            >>> calculator = ImprovedThresholdCalculator()
            >>> threshold = calculator.calculate_adaptive_threshold(
            ...     'balance', 0.15, AttackType.FLASHLOAN, 'amm'
            ... )
            >>> # 0.15 * 0.1 * 1.2 = 0.018 (1.8%)
        """
        # 1. 获取攻击类型的基础系数
        coefficients = self.ATTACK_TYPE_COEFFICIENTS.get(
            attack_type,
            self.ATTACK_TYPE_COEFFICIENTS[AttackType.UNKNOWN]
        )
        base_coefficient = coefficients.get(metric_name, 0.5)

        # 2. 获取协议类型的修正系数
        modifiers = self.PROTOCOL_TYPE_MODIFIERS.get(protocol_type, {})
        protocol_modifier = modifiers.get(metric_name, 1.0)

        # 3. 计算最终系数
        final_coefficient = base_coefficient * protocol_modifier

        # 4. 计算阈值
        threshold = observed_value * final_coefficient

        # 5. 应用最小值约束（避免阈值过小）
        min_values = {
            'loop': 1,           # 循环次数至少为1
            'call_depth': 2,     # 调用深度至少为2
            'balance': 0.0001,   # 余额变化率至少0.01%
        }
        threshold = max(threshold, min_values.get(metric_name, 0))

        # 6. 对于整数类型的指标，向下取整
        if metric_name in ['loop', 'call_depth']:
            threshold = int(threshold)
            # 确保至少为1
            threshold = max(threshold, 1)

        # 记录计算过程
        self.logger.info(
            f"计算阈值 [{metric_name}]: "
            f"observed={observed_value} → threshold={threshold} "
            f"(attack={attack_type.value}, protocol={protocol_type}, "
            f"base_coeff={base_coefficient:.2f}, proto_mod={protocol_modifier:.2f})"
        )

        return threshold

    def get_calculation_metadata(
        self,
        metric_name: str,
        attack_type: AttackType,
        protocol_type: str
    ) -> Dict[str, Any]:
        """
        获取阈值计算的元数据（用于记录到invariants.json）

        Args:
            metric_name: 指标名称
            attack_type: 攻击类型
            protocol_type: 协议类型

        Returns:
            包含计算参数的字典
        """
        coefficients = self.ATTACK_TYPE_COEFFICIENTS.get(
            attack_type,
            self.ATTACK_TYPE_COEFFICIENTS[AttackType.UNKNOWN]
        )
        base_coefficient = coefficients.get(metric_name, 0.5)

        modifiers = self.PROTOCOL_TYPE_MODIFIERS.get(protocol_type, {})
        protocol_modifier = modifiers.get(metric_name, 1.0)

        return {
            'attack_type': attack_type.value,
            'protocol_type': protocol_type,
            'base_coefficient': base_coefficient,
            'protocol_modifier': protocol_modifier,
            'final_coefficient': base_coefficient * protocol_modifier,
            'calculation_method': 'adaptive_threshold'
        }


# ============================================================================
# 工具函数
# ============================================================================

def format_attack_type(attack_type: AttackType) -> str:
    """格式化攻击类型为可读字符串"""
    type_names = {
        AttackType.FLASHLOAN: "闪电贷攻击",
        AttackType.REENTRANCY: "重入攻击",
        AttackType.PRICE_MANIPULATION: "价格操纵",
        AttackType.ACCESS_CONTROL: "访问控制漏洞",
        AttackType.LOGIC_ERROR: "逻辑错误",
        AttackType.UNKNOWN: "未知类型",
    }
    return type_names.get(attack_type, attack_type.value)


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("=" * 80)
    print("ImprovedThresholdCalculator 测试")
    print("=" * 80)

    calculator = ImprovedThresholdCalculator()

    # 测试案例1：重入攻击
    print("\n【测试案例1：重入攻击】")
    monitor_data_reentrancy = {
        'transaction_data': {
            'reentrancy_depth': 3,
            'loop_iterations': 5,
            'call_depth': 12,
            'balance_changes': {
                '0xabc': {'change_rate': 0.05}
            }
        }
    }

    attack_type = calculator.detect_attack_type(monitor_data_reentrancy)
    print(f"检测结果: {format_attack_type(attack_type)}")

    threshold = calculator.calculate_adaptive_threshold(
        'call_depth', 12, attack_type, 'lending'
    )
    print(f"调用深度阈值: {threshold}")

    # 测试案例2：闪电贷攻击
    print("\n【测试案例2：闪电贷攻击】")
    monitor_data_flashloan = {
        'transaction_data': {
            'reentrancy_depth': 0,
            'loop_iterations': 8,
            'call_depth': 10,
            'balance_changes': {
                '0xdef': {'change_rate': 0.25}  # 25%变化
            }
        }
    }

    attack_type = calculator.detect_attack_type(monitor_data_flashloan)
    print(f"检测结果: {format_attack_type(attack_type)}")

    balance_threshold = calculator.calculate_adaptive_threshold(
        'balance', 0.25, attack_type, 'amm'
    )
    print(f"余额变化阈值: {balance_threshold:.4f} ({balance_threshold*100:.2f}%)")

    # 测试案例3：价格操纵
    print("\n【测试案例3：价格操纵】")
    monitor_data_price = {
        'transaction_data': {
            'reentrancy_depth': 0,
            'loop_iterations': 25,
            'call_depth': 18,
            'balance_changes': {
                '0xghi': {'change_rate': 0.08}
            }
        }
    }

    attack_type = calculator.detect_attack_type(monitor_data_price)
    print(f"检测结果: {format_attack_type(attack_type)}")

    loop_threshold = calculator.calculate_adaptive_threshold(
        'loop', 25, attack_type, 'amm'
    )
    print(f"循环次数阈值: {loop_threshold}")

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)
