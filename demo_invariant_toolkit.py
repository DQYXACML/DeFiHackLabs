#!/usr/bin/env python3
"""
Invariant Toolkit 演示脚本

展示新增模块的核心功能:
1. 槽位语义映射
2. 存储布局计算
3. ABI协议检测

运行方式:
    python demo_invariant_toolkit.py
"""

import sys
import json
import logging
from pathlib import Path

# 添加src/test到路径
sys.path.insert(0, str(Path(__file__).parent / "src" / "test"))

from invariant_toolkit.storage_layout import (
    SlotSemanticMapper,
    SlotSemanticType,
    StorageLayoutCalculator,
    StateVariable
)
from invariant_toolkit.protocol_detection import (
    ABIFunctionAnalyzer,
    ProtocolType
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def demo_slot_semantic_mapping():
    """演示1: 槽位语义映射"""
    print("\n" + "="*80)
    print("演示1: 槽位语义映射")
    print("="*80)

    mapper = SlotSemanticMapper()

    # 测试案例
    test_cases = [
        {"name": "totalSupply", "type": "uint256", "value": "0x0de0b6b3a7640000"},
        {"name": "balanceOf", "type": "mapping(address => uint256)", "value": None},
        {"name": "reserve0", "type": "uint112", "value": "0x123456789abcdef"},
        {"name": "underlying", "type": "address", "value": "0x000000000000000000000000c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"},
        {"name": "lastUpdate", "type": "uint256", "value": "0x6385d6a0"},
    ]

    print("\n单个变量映射:")
    for i, case in enumerate(test_cases, 1):
        result = mapper.map_variable_to_semantic(
            variable_name=case["name"],
            variable_type=case.get("type"),
            value=case.get("value")
        )

        print(f"\n{i}. 变量: {case['name']}")
        print(f"   类型: {case.get('type', 'N/A')}")
        print(f"   → 语义类型: {result['semantic_type'].value}")
        print(f"   → 置信度: {result['confidence']:.2f}")
        print(f"   → 原因: {result['reason']}")

    # 批量映射
    print("\n\n批量映射:")
    batch_results = mapper.batch_map_variables(test_cases)
    for var_name, result in batch_results.items():
        print(f"  {var_name:15s} → {result['semantic_type'].value:20s} (conf={result['confidence']:.2f})")


def demo_storage_layout_calculation():
    """演示2: 存储布局计算"""
    print("\n" + "="*80)
    print("演示2: 存储布局计算")
    print("="*80)

    calculator = StorageLayoutCalculator()

    # 模拟ERC20合约的状态变量
    variables = [
        StateVariable(name="owner", var_type="address"),
        StateVariable(name="paused", var_type="bool"),
        StateVariable(name="totalSupply", var_type="uint256"),
        StateVariable(name="balanceOf", var_type="mapping(address => uint256)"),
        StateVariable(name="allowance", var_type="mapping(address => mapping(address => uint256))"),
        StateVariable(name="decimals", var_type="uint8"),
        StateVariable(name="symbol", var_type="string"),
    ]

    # 计算布局
    layout = calculator.calculate_layout(variables)

    print("\n计算的存储布局:")
    print(f"{'变量名':<20s} {'槽位':>6s} {'偏移':>6s} {'大小':>6s} {'类型':<40s}")
    print("-" * 90)

    for var_name, slot_info in layout.items():
        print(
            f"{var_name:<20s} "
            f"{slot_info.slot:>6d} "
            f"{slot_info.offset:>6d} "
            f"{slot_info.size:>6d} "
            f"{slot_info.type:<40s}"
        )

    # 演示packed storage
    print("\n\n✨ Packed Storage示例:")
    print(f"  • owner (address, 20字节) 和 paused (bool, 1字节) 被打包到slot {layout['owner'].slot}")
    print(f"  • owner占用offset 0-19, paused占用offset 20")

    # 演示mapping槽位计算
    print("\n\n🔑 Mapping派生槽位计算:")
    test_address = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
    mapping_slot = calculator.calculate_mapping_slot(
        key=test_address,
        base_slot=layout["balanceOf"].slot,
        key_type="address"
    )
    print(f"  balanceOf[{test_address}]")
    print(f"  → base_slot: {layout['balanceOf'].slot}")
    print(f"  → derived_slot: {mapping_slot}")
    print(f"  → (使用keccak256(key + base_slot)计算)")


def demo_abi_protocol_detection():
    """演示3: ABI协议检测"""
    print("\n" + "="*80)
    print("演示3: ABI协议检测")
    print("="*80)

    analyzer = ABIFunctionAnalyzer()

    # 尝试加载真实的ABI文件
    test_protocols = [
        "extracted_contracts/2024-01/BarleyFinance_exp/0x356e7481b957be0165d6751a49b4b7194aef18d5_Attack_Contract",
        "extracted_contracts/2024-01/XSIJ_exp/0x5313f4f04fdcc2330ccfa5ba7da2780850d1d7be_XSIJ",
        "extracted_contracts/2024-01/MIC_exp/0x92b7807bF19b7C0d818e1E1C6B5297E6B5d4d6e3_BUSDT_USDC",
    ]

    for protocol_dir in test_protocols:
        abi_path = Path(protocol_dir) / "abi.json"

        if not abi_path.exists():
            continue

        print(f"\n\n{'='*80}")
        print(f"分析协议: {protocol_dir.split('/')[-1]}")
        print(f"{'='*80}")

        # 加载ABI
        with open(abi_path) as f:
            abi = json.load(f)

        # 分析协议类型
        result = analyzer.analyze_abi(abi)

        print(f"\n📊 检测结果:")
        print(f"  协议类型: {result['detected_type'].value.upper()}")
        print(f"  置信度: {result['confidence']:.1%}")
        print(f"  函数数量: {result['total_functions']}")

        print(f"\n📈 各协议类型评分:")
        sorted_scores = sorted(
            result['protocol_scores'].items(),
            key=lambda x: x[1],
            reverse=True
        )
        for protocol, score in sorted_scores[:5]:
            if score > 0:
                bar = "█" * int(score * 20)
                print(f"  {protocol:15s} {score:>6.1%} {bar}")

        # 检测ERC标准
        standards = analyzer.detect_erc_standards(abi)
        if standards:
            print(f"\n✅ 实现的ERC标准: {', '.join(standards)}")

        # 识别关键函数
        critical = analyzer.get_critical_functions(abi)
        print(f"\n🔐 关键函数识别:")
        for category, functions in critical.items():
            if functions:
                print(f"  {category:20s}: {len(functions)}个")
                print(f"    → {', '.join(functions[:5])}")
                if len(functions) > 5:
                    print(f"      ... 以及其他 {len(functions) - 5} 个")


def demo_integration_example():
    """演示4: 集成示例"""
    print("\n" + "="*80)
    print("演示4: 集成示例 - BarleyFinance完整分析流程")
    print("="*80)

    project_dir = Path("extracted_contracts/2024-01/BarleyFinance_exp")

    # 步骤1: 加载合约元数据
    main_contract = "0x356e7481b957be0165d6751a49b4b7194aef18d5_Attack_Contract"
    contract_dir = project_dir / main_contract

    if not contract_dir.exists():
        print(f"\n⚠️ 测试目录不存在: {contract_dir}")
        print("   跳过集成演示")
        return

    print(f"\n📂 分析项目: BarleyFinance_exp")
    print(f"   合约目录: {main_contract}")

    # 步骤2: ABI分析
    abi_path = contract_dir / "abi.json"
    if abi_path.exists():
        with open(abi_path) as f:
            abi = json.load(f)

        analyzer = ABIFunctionAnalyzer()
        protocol_result = analyzer.analyze_abi(abi)

        print(f"\n✅ 协议检测: {protocol_result['detected_type'].value} (置信度: {protocol_result['confidence']:.1%})")

    # 步骤3: 加载attack_state分析槽位
    attack_state_path = project_dir / "attack_state.json"
    if attack_state_path.exists():
        with open(attack_state_path) as f:
            attack_state = json.load(f)

        contract_address = "0x356e7481b957be0165d6751a49b4b7194aef18d5"
        if contract_address in attack_state.get("addresses", {}):
            storage = attack_state["addresses"][contract_address].get("storage", {})

            print(f"\n📊 存储槽位分析:")
            print(f"   合约: {contract_address[:10]}...")
            print(f"   槽位数量: {len(storage)}")

            # 使用语义映射器分析槽位
            mapper = SlotSemanticMapper()

            # 简化示例: 分析slot 2 (通常是totalSupply)
            if "2" in storage or "0x2" in storage:
                slot_2_value = storage.get("2") or storage.get("0x2")
                result = mapper.map_variable_to_semantic(
                    variable_name="totalSupply",  # 推断
                    variable_type="uint256",
                    value=slot_2_value
                )

                print(f"\n   Slot 2分析:")
                print(f"   → 值: {slot_2_value[:20]}...")
                print(f"   → 推断类型: {result['semantic_type'].value}")
                print(f"   → 置信度: {result['confidence']:.2f}")

    # 步骤4: 总结
    print(f"\n\n💡 下一步:")
    print(f"   1. 使用ProtocolDetectorV2融合多种信息源")
    print(f"   2. 使用StateDiffCalculator对比before/after状态")
    print(f"   3. 使用ComplexInvariantGenerator生成业务逻辑不变量")


def main():
    """主函数"""
    print("\n" + "="*80)
    print(" Invariant Toolkit 演示程序 v2.0")
    print("="*80)
    print("\n本演示展示新增的三个核心模块:")
    print("  1. 槽位语义映射器 (SlotSemanticMapper)")
    print("  2. 存储布局计算器 (StorageLayoutCalculator)")
    print("  3. ABI函数分析器 (ABIFunctionAnalyzer)")

    try:
        # 演示1: 槽位语义映射
        demo_slot_semantic_mapping()

        # 演示2: 存储布局计算
        demo_storage_layout_calculation()

        # 演示3: ABI协议检测
        demo_abi_protocol_detection()

        # 演示4: 集成示例
        demo_integration_example()

        print("\n" + "="*80)
        print("✅ 演示完成!")
        print("="*80)
        print("\n📚 更多信息请参考:")
        print("   - INVARIANT_TOOLKIT_IMPLEMENTATION_REPORT.md")
        print("   - src/test/invariant_toolkit/")

    except Exception as e:
        logger.error(f"演示过程中出错: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
