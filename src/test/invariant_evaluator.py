#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
不变量评估引擎

功能：实现所有不变量类型的检测逻辑
支持的不变量类型：
- share_price_stability: 份额价格稳定性
- supply_backing_consistency: 供应支撑一致性
- bounded_change_rate: 变化率限制
- balance_change_rate: 余额变化率
- loop_iterations: 循环迭代次数
- flash_loan_depth: 闪电贷深度
- call_sequence_pattern: 调用序列模式
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ViolationSeverity(Enum):
    """违规严重程度"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ViolationResult:
    """不变量违规结果"""
    invariant_id: str
    invariant_type: str
    severity: ViolationSeverity
    violated: bool
    threshold: Any
    actual_value: Any
    description: str
    impact: str
    evidence: Dict[str, Any]
    confidence: float = 1.0


class InvariantEvaluator:
    """不变量评估器主类"""

    def __init__(self):
        """初始化评估器"""
        self.evaluators = {
            'share_price_stability': self._eval_share_price_stability,
            'supply_backing_consistency': self._eval_supply_backing_consistency,
            'bounded_change_rate': self._eval_bounded_change_rate,
            'balance_change_rate': self._eval_balance_change_rate,
            'loop_iterations': self._eval_loop_iterations,
            'flash_loan_depth': self._eval_flash_loan_depth,
            'call_sequence_pattern': self._eval_call_sequence_pattern,
        }

    def evaluate_all(
        self,
        invariants: List[Dict],
        storage_changes: Dict,
        runtime_metrics: Optional[Dict] = None
    ) -> List[ViolationResult]:
        """
        评估所有不变量

        Args:
            invariants: 不变量规则列表
            storage_changes: 存储变化数据
            runtime_metrics: 运行时指标数据（可选）

        Returns:
            违规结果列表
        """
        results = []

        for invariant in invariants:
            inv_type = invariant.get('type')

            if inv_type not in self.evaluators:
                logger.warning(f"未知的不变量类型: {inv_type}")
                continue

            try:
                # 根据类型选择存储级或运行时评估
                if inv_type in ['share_price_stability', 'supply_backing_consistency', 'bounded_change_rate']:
                    result = self.evaluators[inv_type](invariant, storage_changes)
                else:
                    if runtime_metrics is None:
                        logger.warning(f"运行时不变量 {inv_type} 需要 runtime_metrics，已跳过")
                        continue
                    result = self.evaluators[inv_type](invariant, runtime_metrics, storage_changes)

                results.append(result)

                if result.violated:
                    logger.warning(
                        f"检测到违规: [{result.invariant_id}] {result.invariant_type} "
                        f"(实际值: {result.actual_value}, 阈值: {result.threshold})"
                    )
                else:
                    logger.info(f"通过检测: [{result.invariant_id}] {result.invariant_type}")

            except Exception as e:
                logger.error(f"评估不变量 {invariant.get('id', 'unknown')} 时出错: {e}")
                continue

        return results

    # ==================== 存储级不变量评估 ====================

    def _eval_share_price_stability(
        self,
        invariant: Dict,
        storage_changes: Dict
    ) -> ViolationResult:
        """
        评估份额价格稳定性（Vault攻击检测）

        公式: |(reserves/totalSupply)_after - (reserves/totalSupply)_before|
              / (reserves/totalSupply)_before <= threshold
        """
        slots = invariant.get('slots', {})

        # 提取totalSupply变化
        supply_contract = slots.get('totalSupply_contract')
        supply_slot = int(slots.get('totalSupply_slot', 0))

        supply_before = storage_changes.get(supply_contract, {}).get(supply_slot, {}).get('before', 0)
        supply_after = storage_changes.get(supply_contract, {}).get(supply_slot, {}).get('after', 0)

        # 提取reserves变化（可能是合约余额）
        reserves_contract = slots.get('reserves_contract')

        # reserves可能是存储槽或者是合约余额
        if 'reserves_slot' in slots:
            reserves_slot = int(slots['reserves_slot'])
            reserves_before = storage_changes.get(reserves_contract, {}).get(reserves_slot, {}).get('before', 0)
            reserves_after = storage_changes.get(reserves_contract, {}).get(reserves_slot, {}).get('after', 0)
        else:
            # 从余额变化中提取
            reserves_before = storage_changes.get('balances', {}).get(reserves_contract, {}).get('before', 0)
            reserves_after = storage_changes.get('balances', {}).get(reserves_contract, {}).get('after', 0)

        # 计算份额价格
        price_before = reserves_before / supply_before if supply_before > 0 else 0
        price_after = reserves_after / supply_after if supply_after > 0 else 0

        # 计算变化率
        change_rate = abs(price_after - price_before) / price_before if price_before > 0 else float('inf')

        # 检查是否违规
        threshold = invariant.get('threshold', 0.05)
        is_violated = change_rate > threshold

        return ViolationResult(
            invariant_id=invariant.get('id', 'UNKNOWN'),
            invariant_type='share_price_stability',
            severity=ViolationSeverity(invariant.get('severity', 'critical')),
            violated=is_violated,
            threshold=f"{threshold * 100:.1f}%",
            actual_value=f"{change_rate * 100:.1f}%",
            description=invariant.get('description', ''),
            impact=invariant.get('violation_impact', ''),
            evidence={
                'totalSupply_before': supply_before,
                'totalSupply_after': supply_after,
                'totalSupply_change_pct': f"{abs(supply_after - supply_before) / supply_before * 100:.1f}%" if supply_before > 0 else 'N/A',
                'reserves_before': reserves_before,
                'reserves_after': reserves_after,
                'reserves_change_pct': f"{abs(reserves_after - reserves_before) / reserves_before * 100:.1f}%" if reserves_before > 0 else 'N/A',
                'share_price_before': f"{price_before:.6f}",
                'share_price_after': f"{price_after:.6f}",
                'share_price_change_pct': f"{change_rate * 100:.1f}%"
            },
            confidence=invariant.get('confidence', 1.0)
        )

    def _eval_supply_backing_consistency(
        self,
        invariant: Dict,
        storage_changes: Dict
    ) -> ViolationResult:
        """
        评估供应支撑一致性

        公式: totalSupply <= reserves * max_leverage_ratio
        """
        slots = invariant.get('slots', {})

        # 提取totalSupply（after状态）
        supply_contract = slots.get('totalSupply_contract')
        supply_slot = int(slots.get('totalSupply_slot', 0))
        supply_after = storage_changes.get(supply_contract, {}).get(supply_slot, {}).get('after', 0)

        # 提取reserves（after状态）
        reserves_contract = slots.get('reserves_contract')
        if 'reserves_slot' in slots:
            reserves_slot = int(slots['reserves_slot'])
            reserves_after = storage_changes.get(reserves_contract, {}).get(reserves_slot, {}).get('after', 0)
        else:
            reserves_after = storage_changes.get('balances', {}).get(reserves_contract, {}).get('after', 0)

        # 计算实际杠杆率
        actual_ratio = supply_after / reserves_after if reserves_after > 0 else float('inf')

        # 检查是否违规
        max_ratio = invariant.get('threshold', 1.1)
        is_violated = actual_ratio > max_ratio

        return ViolationResult(
            invariant_id=invariant.get('id', 'UNKNOWN'),
            invariant_type='supply_backing_consistency',
            severity=ViolationSeverity(invariant.get('severity', 'high')),
            violated=is_violated,
            threshold=f"{max_ratio:.2f}",
            actual_value=f"{actual_ratio:.2f}",
            description=invariant.get('description', ''),
            impact=invariant.get('violation_impact', ''),
            evidence={
                'totalSupply': supply_after,
                'reserves': reserves_after,
                'leverage_ratio': f"{actual_ratio:.2f}",
                'max_allowed_ratio': f"{max_ratio:.2f}"
            },
            confidence=invariant.get('confidence', 1.0)
        )

    def _eval_bounded_change_rate(
        self,
        invariant: Dict,
        storage_changes: Dict
    ) -> ViolationResult:
        """
        评估变化率限制

        公式: |slot_after - slot_before| / slot_before <= threshold
        """
        slots = invariant.get('slots', {})

        contract = slots.get('contract') or invariant.get('contracts', [None])[0]
        slot = int(slots.get('monitored_slot', 0))

        value_before = storage_changes.get(contract, {}).get(slot, {}).get('before', 0)
        value_after = storage_changes.get(contract, {}).get(slot, {}).get('after', 0)

        # 计算变化率
        change_rate = abs(value_after - value_before) / value_before if value_before > 0 else float('inf')

        # 检查是否违规
        threshold = invariant.get('threshold', 0.5)
        is_violated = change_rate > threshold

        return ViolationResult(
            invariant_id=invariant.get('id', 'UNKNOWN'),
            invariant_type='bounded_change_rate',
            severity=ViolationSeverity(invariant.get('severity', 'medium')),
            violated=is_violated,
            threshold=f"{threshold * 100:.1f}%",
            actual_value=f"{change_rate * 100:.1f}%",
            description=invariant.get('description', ''),
            impact=invariant.get('violation_impact', ''),
            evidence={
                'contract': contract,
                'slot': slot,
                'value_before': value_before,
                'value_after': value_after,
                'absolute_change': value_after - value_before,
                'change_rate': f"{change_rate * 100:.1f}%"
            },
            confidence=invariant.get('confidence', 1.0)
        )

    # ==================== 运行时不变量评估 ====================

    def _eval_balance_change_rate(
        self,
        invariant: Dict,
        runtime_metrics: Dict,
        storage_changes: Dict
    ) -> ViolationResult:
        """
        评估余额变化率（攻击者获利检测）

        公式: (balance_after - balance_before) / balance_before <= threshold
        """
        # 从runtime_metrics中提取余额变化
        balance_changes = runtime_metrics.get('balance_changes', {})

        # 通常检测攻击者地址的余额变化
        # 如果不变量中指定了地址，使用指定地址；否则找变化最大的
        target_address = invariant.get('metadata', {}).get('target_address')

        if target_address:
            change_data = balance_changes.get(target_address.lower(), {})
        else:
            # 找到余额变化最大的地址
            max_change = 0
            change_data = {}
            for addr, data in balance_changes.items():
                change = abs(data.get('change_rate', 0))
                if change > max_change:
                    max_change = change
                    change_data = data

        change_rate = change_data.get('change_rate', 0)

        # 检查是否违规
        threshold = invariant.get('threshold', 5.0)  # 默认500%
        is_violated = abs(change_rate) > threshold

        return ViolationResult(
            invariant_id=invariant.get('id', 'UNKNOWN'),
            invariant_type='balance_change_rate',
            severity=ViolationSeverity(invariant.get('severity', 'high')),
            violated=is_violated,
            threshold=f"{threshold * 100:.0f}%",
            actual_value=f"{change_rate * 100:.0f}%",
            description=invariant.get('description', ''),
            impact=invariant.get('violation_impact', ''),
            evidence={
                'balance_before': change_data.get('before', 0),
                'balance_after': change_data.get('after', 0),
                'difference': change_data.get('difference', 0),
                'change_rate': f"{change_rate * 100:.1f}%"
            },
            confidence=invariant.get('confidence', 1.0)
        )

    def _eval_loop_iterations(
        self,
        invariant: Dict,
        runtime_metrics: Dict,
        storage_changes: Dict
    ) -> ViolationResult:
        """
        评估循环迭代次数

        检测: loop_iterations > threshold
        """
        actual_iterations = runtime_metrics.get('loop_iterations', 0)
        threshold = invariant.get('threshold', 5)

        is_violated = actual_iterations > threshold

        # 提取循环相关的函数调用信息
        function_calls = runtime_metrics.get('function_calls', {})
        max_call_count = max(function_calls.values()) if function_calls else 0
        most_called_func = max(function_calls, key=function_calls.get) if function_calls else 'N/A'

        return ViolationResult(
            invariant_id=invariant.get('id', 'UNKNOWN'),
            invariant_type='loop_iterations',
            severity=ViolationSeverity(invariant.get('severity', 'high')),
            violated=is_violated,
            threshold=threshold,
            actual_value=actual_iterations,
            description=invariant.get('description', ''),
            impact=invariant.get('violation_impact', ''),
            evidence={
                'detected_iterations': actual_iterations,
                'most_called_function': most_called_func,
                'max_call_count': max_call_count,
                'all_function_calls': function_calls
            },
            confidence=invariant.get('confidence', 1.0)
        )

    def _eval_flash_loan_depth(
        self,
        invariant: Dict,
        runtime_metrics: Dict,
        storage_changes: Dict
    ) -> ViolationResult:
        """
        评估闪电贷深度（嵌套闪电贷检测）

        检测: reentrancy_depth > threshold
        """
        actual_depth = runtime_metrics.get('reentrancy_depth', 0)
        threshold = invariant.get('threshold', 2)

        is_violated = actual_depth > threshold

        return ViolationResult(
            invariant_id=invariant.get('id', 'UNKNOWN'),
            invariant_type='flash_loan_depth',
            severity=ViolationSeverity(invariant.get('severity', 'medium')),
            violated=is_violated,
            threshold=threshold,
            actual_value=actual_depth,
            description=invariant.get('description', ''),
            impact=invariant.get('violation_impact', ''),
            evidence={
                'reentrancy_depth': actual_depth,
                'call_depth': runtime_metrics.get('call_depth', 0)
            },
            confidence=invariant.get('confidence', 1.0)
        )

    def _eval_call_sequence_pattern(
        self,
        invariant: Dict,
        runtime_metrics: Dict,
        storage_changes: Dict
    ) -> ViolationResult:
        """
        评估调用序列模式（检测可疑的callback重入模式）

        检测: 是否存在特定的函数调用模式
        """
        call_sequence = runtime_metrics.get('call_sequence', [])

        # 检查是否存在不变量中定义的恶意模式
        suspicious_patterns = invariant.get('metadata', {}).get('suspicious_patterns', [])

        detected_patterns = []
        for pattern in suspicious_patterns:
            # 简单的模式匹配：检查pattern是否作为子序列出现
            pattern_list = pattern if isinstance(pattern, list) else [pattern]
            if self._is_subsequence(pattern_list, call_sequence):
                detected_patterns.append(pattern)

        is_violated = len(detected_patterns) > 0

        return ViolationResult(
            invariant_id=invariant.get('id', 'UNKNOWN'),
            invariant_type='call_sequence_pattern',
            severity=ViolationSeverity(invariant.get('severity', 'medium')),
            violated=is_violated,
            threshold=f"No suspicious patterns",
            actual_value=f"{len(detected_patterns)} pattern(s) detected",
            description=invariant.get('description', ''),
            impact=invariant.get('violation_impact', ''),
            evidence={
                'detected_patterns': detected_patterns,
                'call_sequence_length': len(call_sequence),
                'call_sequence_preview': call_sequence[:20] if len(call_sequence) > 20 else call_sequence
            },
            confidence=invariant.get('confidence', 0.8)
        )

    def _is_subsequence(self, pattern: List[str], sequence: List[str]) -> bool:
        """检查pattern是否是sequence的子序列"""
        if not pattern:
            return True

        pattern_idx = 0
        for item in sequence:
            if item == pattern[pattern_idx]:
                pattern_idx += 1
                if pattern_idx == len(pattern):
                    return True

        return False


if __name__ == '__main__':
    # 测试示例
    evaluator = InvariantEvaluator()

    # 示例不变量
    test_invariants = [
        {
            'id': 'SINV_001',
            'type': 'share_price_stability',
            'severity': 'critical',
            'description': 'Vault share price must not change more than 5% per transaction',
            'threshold': 0.05,
            'slots': {
                'totalSupply_contract': '0xABC',
                'totalSupply_slot': '2',
                'reserves_contract': '0xDEF'
            }
        }
    ]

    # 示例存储变化
    test_storage_changes = {
        '0xABC': {
            2: {
                'before': 1000000,
                'after': 1500000
            }
        },
        'balances': {
            '0xDEF': {
                'before': 5000000,
                'after': 3000000
            }
        }
    }

    results = evaluator.evaluate_all(test_invariants, test_storage_changes)

    for result in results:
        print(f"\n{'='*60}")
        print(f"不变量ID: {result.invariant_id}")
        print(f"类型: {result.invariant_type}")
        print(f"严重程度: {result.severity.value}")
        print(f"违规: {'是' if result.violated else '否'}")
        print(f"阈值: {result.threshold}")
        print(f"实际值: {result.actual_value}")
        print(f"证据: {result.evidence}")
