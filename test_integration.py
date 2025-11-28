#!/usr/bin/env python3
"""
集成测试脚本

在真实DeFi协议案例上测试InvariantGeneratorV2的效果。
"""

import sys
import json
import logging
from pathlib import Path
from typing import List

# 添加src/test到路径
sys.path.insert(0, str(Path(__file__).parent / "src" / "test"))

from invariant_toolkit import InvariantGeneratorV2

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_single_protocol(protocol_name: str):
    """测试单个协议"""
    print(f"\n{'='*80}")
    print(f"测试协议: {protocol_name}")
    print(f"{'='*80}\n")

    project_dir = Path(f"extracted_contracts/2024-01/{protocol_name}")

    if not project_dir.exists():
        print(f"⚠️  项目目录不存在: {project_dir}")
        return None

    # 创建生成器
    generator = InvariantGeneratorV2()

    # 生成不变量
    result = generator.generate_from_project(project_dir)

    # 打印结果
    print(f"\n📊 生成结果:")
    print(f"  协议类型: {result.get('protocol_type', 'unknown')}")
    print(f"  置信度: {result.get('protocol_confidence', 0):.2%}")

    if "state_changes" in result:
        print(f"\n🔄 状态变化:")
        print(f"  合约数: {result['state_changes']['contracts_changed']}")
        print(f"  槽位变化: {result['state_changes']['slots_changed']}")
        print(f"  极端变化: {result['state_changes']['extreme_changes']}")

    if "attack_patterns" in result:
        print(f"\n🚨 攻击模式:")
        for pattern in result["attack_patterns"][:5]:
            print(f"  - {pattern['type']}: {pattern['description'][:60]}...")
            print(f"    严重性: {pattern['severity']}, 置信度: {pattern['confidence']:.2%}")

    stats = result.get("statistics", {})
    print(f"\n✅ 不变量统计:")
    print(f"  总数: {stats.get('total_invariants', 0)}")

    if "by_category" in stats:
        print(f"\n  按类别:")
        for category, count in sorted(stats["by_category"].items()):
            print(f"    {category}: {count}")

    if "by_severity" in stats:
        print(f"\n  按严重性:")
        for severity, count in sorted(stats["by_severity"].items(), reverse=True):
            print(f"    {severity}: {count}")

    # 显示前3个不变量示例
    if result.get("invariants"):
        print(f"\n📋 不变量示例 (前3个):")
        for i, inv in enumerate(result["invariants"][:3], 1):
            print(f"\n  {i}. {inv['type']} ({inv['category']})")
            print(f"     描述: {inv['description'][:70]}...")
            print(f"     公式: {inv['formula'][:80]}...")
            print(f"     严重性: {inv['severity']}, 阈值: {inv['threshold']}")

    return result


def compare_with_v1(protocol_name: str):
    """对比v1.0的结果"""
    print(f"\n{'='*80}")
    print(f"对比v1.0 vs v2.0: {protocol_name}")
    print(f"{'='*80}\n")

    project_dir = Path(f"extracted_contracts/2024-01/{protocol_name}")

    # 加载v1.0结果 (如果存在)
    v1_path = project_dir / "invariants.json"
    v2_path = project_dir / "invariants_v2.json"

    if not v1_path.exists():
        print(f"⚠️  v1.0结果不存在: {v1_path}")
        return

    if not v2_path.exists():
        print(f"⚠️  v2.0结果不存在,请先运行test_single_protocol()")
        return

    with open(v1_path, 'r') as f:
        v1_data = json.load(f)

    with open(v2_path, 'r') as f:
        v2_data = json.load(f)

    # 统计v1.0
    v1_storage = v1_data.get("storage_invariants", [])
    v1_runtime = v1_data.get("runtime_invariants", [])
    v1_total = len(v1_storage) + len(v1_runtime)

    # 统计v2.0
    v2_total = v2_data.get("statistics", {}).get("total_invariants", 0)
    v2_by_category = v2_data.get("statistics", {}).get("by_category", {})

    print(f"📊 数量对比:")
    print(f"  v1.0 总数: {v1_total} (存储: {len(v1_storage)}, 运行时: {len(v1_runtime)})")
    print(f"  v2.0 总数: {v2_total}")
    print(f"  增长: +{v2_total - v1_total} ({((v2_total / v1_total - 1) * 100 if v1_total > 0 else 0):.1f}%)")

    print(f"\n📈 v1.0 不变量类型:")
    v1_types = {}
    for inv in v1_storage:
        inv_type = inv.get("type", "unknown")
        v1_types[inv_type] = v1_types.get(inv_type, 0) + 1
    for inv_type, count in sorted(v1_types.items()):
        print(f"  {inv_type}: {count}")

    print(f"\n📈 v2.0 不变量类别:")
    for category, count in sorted(v2_by_category.items()):
        print(f"  {category}: {count}")

    print(f"\n✨ v2.0 新增能力:")
    print(f"  ✓ 协议特定业务逻辑不变量")
    print(f"  ✓ 跨合约关系不变量")
    print(f"  ✓ 基于攻击模式的防御性不变量")
    print(f"  ✓ 槽位语义识别 (覆盖率: {v2_data.get('semantic_mapping_coverage', 0):.1%})")


def batch_test(protocol_list: List[str]):
    """批量测试多个协议"""
    print(f"\n{'='*80}")
    print(f"批量测试: {len(protocol_list)} 个协议")
    print(f"{'='*80}\n")

    results_summary = []

    for protocol in protocol_list:
        try:
            result = test_single_protocol(protocol)
            if result and "error" not in result:
                results_summary.append({
                    "protocol": protocol,
                    "type": result.get("protocol_type"),
                    "total": result.get("statistics", {}).get("total_invariants", 0),
                    "success": True
                })
            else:
                results_summary.append({
                    "protocol": protocol,
                    "success": False,
                    "error": result.get("errors", ["Unknown error"])[0] if result else "Failed"
                })
        except Exception as e:
            logger.error(f"处理 {protocol} 时出错: {e}")
            results_summary.append({
                "protocol": protocol,
                "success": False,
                "error": str(e)
            })

    # 打印汇总
    print(f"\n{'='*80}")
    print(f"批量测试汇总")
    print(f"{'='*80}\n")

    successful = [r for r in results_summary if r["success"]]
    failed = [r for r in results_summary if not r["success"]]

    print(f"成功: {len(successful)}/{len(protocol_list)}")
    print(f"失败: {len(failed)}/{len(protocol_list)}")

    if successful:
        print(f"\n✅ 成功的协议:")
        for r in successful:
            print(f"  {r['protocol']:30s} {r['type']:15s} {r['total']:3d} 个不变量")

        total_invariants = sum(r["total"] for r in successful)
        avg_invariants = total_invariants / len(successful)
        print(f"\n  平均每个协议: {avg_invariants:.1f} 个不变量")

    if failed:
        print(f"\n❌ 失败的协议:")
        for r in failed:
            print(f"  {r['protocol']:30s} {r.get('error', 'Unknown error')[:50]}")


def main():
    """主函数"""
    print(f"\n{'='*80}")
    print(f" InvariantGeneratorV2 集成测试")
    print(f"{'='*80}\n")

    # 测试协议列表 (选择有attack_state的协议)
    test_protocols = [
        "BarleyFinance_exp",
        "XSIJ_exp",
        "MIC_exp",
        # 可以添加更多...
    ]

    # 单个协议详细测试
    print("\n" + "="*80)
    print("阶段1: 单个协议详细测试")
    print("="*80)

    for protocol in test_protocols[:1]:  # 先测试第一个
        result = test_single_protocol(protocol)
        if result:
            compare_with_v1(protocol)

    # 批量测试
    if len(test_protocols) > 1:
        print("\n" + "="*80)
        print("阶段2: 批量测试")
        print("="*80)
        batch_test(test_protocols)

    print(f"\n{'='*80}")
    print(f"✅ 集成测试完成!")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
