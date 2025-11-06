#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试动态检测系统的各个组件
"""

import sys
from pathlib import Path

# 添加路径
sys.path.append(str(Path(__file__).parent))

def test_scan():
    """测试扫描功能"""
    print("=" * 70)
    print("测试1: 扫描2024-01目录下的攻击")
    print("=" * 70)

    from batch_dynamic_checker import BatchDynamicChecker

    checker = BatchDynamicChecker(workers=1)
    attacks = checker._scan_attacks(filter_year_month="2024-01", event_names=None)

    print(f"\n找到 {len(attacks)} 个可检测的攻击:")
    for attack in attacks:
        print(f"  ✓ {attack.year_month}/{attack.event_name}")

    return len(attacks) > 0

def test_invariant_evaluator():
    """测试不变量评估器"""
    print("\n" + "=" * 70)
    print("测试2: 不变量评估器")
    print("=" * 70)

    from invariant_evaluator import InvariantEvaluator

    evaluator = InvariantEvaluator()

    # 测试不变量
    test_invariants = [
        {
            'id': 'TEST_001',
            'type': 'bounded_change_rate',
            'severity': 'high',
            'description': '测试变化率限制',
            'threshold': 0.5,
            'slots': {
                'contract': '0xABC',
                'monitored_slot': '2'
            }
        }
    ]

    # 测试存储变化
    test_storage_changes = {
        '0xABC': {
            2: {
                'before': 1000,
                'after': 2000,
                'change_abs': 1000,
                'change_rate': 1.0
            }
        }
    }

    results = evaluator.evaluate_all(test_invariants, test_storage_changes)

    print(f"\n评估结果:")
    for result in results:
        status = "违规 ❌" if result.violated else "通过 ✅"
        print(f"  [{result.invariant_id}] {result.invariant_type}: {status}")
        print(f"    阈值: {result.threshold}, 实际: {result.actual_value}")

    return len(results) > 0

def test_storage_comparator():
    """测试存储对比器"""
    print("\n" + "=" * 70)
    print("测试3: 存储对比器")
    print("=" * 70)

    from storage_comparator import StorageComparator

    comparator = StorageComparator()

    # 测试提取存储槽
    test_invariants = [
        {
            'id': 'TEST_001',
            'type': 'share_price_stability',
            'slots': {
                'totalSupply_contract': '0x123',
                'totalSupply_slot': '2',
                'reserves_contract': '0x456'
            }
        }
    ]

    slots = comparator.extract_slots_from_invariants(test_invariants)

    print(f"\n提取到 {len(slots)} 个存储槽:")
    for contract, slot in slots:
        print(f"  {contract} slot {slot}")

    # 测试快照对比
    snapshot_before = {
        'storage': {
            '0x123': {2: 1000}
        },
        'balances': {
            '0x456': 5000
        }
    }

    snapshot_after = {
        'storage': {
            '0x123': {2: 1500}
        },
        'balances': {
            '0x456': 3000
        }
    }

    changes = comparator.compare_snapshots(snapshot_before, snapshot_after)

    print(f"\n存储变化:")
    for contract, slots in changes.items():
        if contract == 'balances':
            continue
        for slot, data in slots.items():
            print(f"  {contract}[{slot}]: {data['before']} → {data['after']} ({data['change_pct']})")

    return True

def test_report_builder():
    """测试报告生成器"""
    print("\n" + "=" * 70)
    print("测试4: 报告生成器")
    print("=" * 70)

    from report_builder import ReportBuilder
    from invariant_evaluator import ViolationResult, ViolationSeverity

    builder = ReportBuilder(
        event_name="TestAttack",
        year_month="2024-01",
        output_dir=Path("/tmp/test_dynamic_reports")
    )

    # 创建测试违规结果
    test_results = [
        ViolationResult(
            invariant_id='TEST_001',
            invariant_type='share_price_stability',
            severity=ViolationSeverity.CRITICAL,
            violated=True,
            threshold='5%',
            actual_value='87.3%',
            description='测试份额价格稳定性',
            impact='允许攻击者铸造低价份额',
            evidence={'price_before': 5.0, 'price_after': 2.0}
        ),
        ViolationResult(
            invariant_id='TEST_002',
            invariant_type='bounded_change_rate',
            severity=ViolationSeverity.HIGH,
            violated=False,
            threshold='50%',
            actual_value='30%',
            description='测试变化率限制',
            impact='N/A',
            evidence={'value_before': 1000, 'value_after': 1300}
        )
    ]

    builder.build_report(
        invariants=[],
        violation_results=test_results,
        storage_changes={},
        runtime_metrics={'gas_used': 1000000},
        attack_tx_hash='0x123...'
    )

    # 检查文件是否生成
    md_file = builder.output_dir / "TestAttack_dynamic_report.md"
    json_file = builder.output_dir / "TestAttack_dynamic_report.json"

    md_exists = md_file.exists()
    json_exists = json_file.exists()

    print(f"\n报告文件:")
    print(f"  Markdown: {md_file} {'✓' if md_exists else '✗'}")
    print(f"  JSON: {json_file} {'✓' if json_exists else '✗'}")

    if md_exists:
        # 显示前几行
        with open(md_file, 'r') as f:
            lines = f.readlines()[:10]
            print(f"\nMarkdown预览:")
            for line in lines:
                print(f"  {line.rstrip()}")

    return md_exists and json_exists

def main():
    """运行所有测试"""
    print("\n🧪 动态检测系统组件测试\n")

    tests = [
        ("扫描功能", test_scan),
        ("不变量评估器", test_invariant_evaluator),
        ("存储对比器", test_storage_comparator),
        ("报告生成器", test_report_builder)
    ]

    results = []

    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # 汇总
    print("\n" + "=" * 70)
    print("测试汇总")
    print("=" * 70)

    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {name}: {status}")

    total_passed = sum(1 for _, success in results if success)
    print(f"\n总计: {total_passed}/{len(results)} 通过")

    return total_passed == len(results)

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
