#!/usr/bin/env python3
"""
测试OnChainDataFetcher集成到extract_contracts的功能

测试流程:
1. 创建模拟的ContractAddress对象
2. 使用_enrich_with_onchain_data补全
3. 验证结果
"""

import sys
from pathlib import Path
import json

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src" / "test"))

# 直接导入extract_contracts模块
import extract_contracts
ContractExtractor = extract_contracts.ContractExtractor
ContractAddress = extract_contracts.ContractAddress

def test_onchain_enrichment():
    """测试链上数据补全功能"""
    print("=" * 80)
    print("测试 OnChainDataFetcher 集成")
    print("=" * 80)
    print()

    # 创建提取器实例
    test_dir = Path("src/test")
    output_dir = Path("extracted_contracts")

    extractor = ContractExtractor(
        test_dir=test_dir,
        output_dir=output_dir
    )

    # 创建测试地址列表 (BarleyFinance地址)
    test_addresses = [
        ContractAddress(
            address="0x04c80Bb477890F3021F03B068238836Ee20aA0b8",
            name="IwBARL",  # 接口名(模拟从AST提取)
            chain="mainnet",
            source="static"
        ),
        ContractAddress(
            address="0x3e2324342bF5B8A1Dca42915f0489497203d640E",
            name="IBARL",
            chain="mainnet",
            source="static"
        ),
        ContractAddress(
            address="0x6B175474E89094C44Da98b954EedeAC495271d0F",
            name="DAI",
            chain="mainnet",
            source="static"
        ),
    ]

    print(f"待补全地址: {len(test_addresses)}个")
    for addr in test_addresses:
        print(f"  - {addr.address[:10]}... (name={addr.name})")
    print()

    # 补全链上数据
    print("开始补全链上数据...")
    enriched = extractor._enrich_with_onchain_data(test_addresses, "mainnet")

    # 显示结果
    print()
    print("补全结果:")
    print("=" * 80)

    for i, addr in enumerate(enriched, 1):
        print(f"\n地址 {i}: {addr.address}")
        print(f"  原始名称:      {addr.name}")
        print(f"  链上名称:      {addr.onchain_name}")
        print(f"  Symbol:       {addr.symbol}")
        print(f"  Decimals:     {addr.decimals}")
        print(f"  是否ERC20:    {addr.is_erc20}")
        print(f"  语义类型:      {addr.semantic_type}")
        print(f"  别名列表:      {addr.aliases}")

    # 保存结果到JSON
    output_file = output_dir / "test_onchain_integration_result.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    data = [vars(addr) for addr in enriched]
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)

    print()
    print("=" * 80)
    print(f"✅ 测试完成! 结果已保存到: {output_file}")
    print("=" * 80)

    # 验证关键字段
    print()
    print("验证结果:")
    wbarl = enriched[0]
    if wbarl.symbol == "wBARL" and wbarl.is_erc20 and "IwBARL" in wbarl.aliases:
        print("✅ wBARL地址补全正确")
        print(f"   - Symbol: {wbarl.symbol}")
        print(f"   - 别名包含IwBARL: {'IwBARL' in wbarl.aliases}")
        print(f"   - 语义类型: {wbarl.semantic_type}")
    else:
        print("❌ wBARL地址补全失败")
        print(f"   - Symbol: {wbarl.symbol} (期望: wBARL)")
        print(f"   - 别名: {wbarl.aliases}")

if __name__ == "__main__":
    test_onchain_enrichment()
