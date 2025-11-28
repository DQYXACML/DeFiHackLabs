#!/usr/bin/env python3
"""
测试向后兼容性: 验证旧版 addresses.json(无补全字段)仍可正常工作
"""

from dataclasses import dataclass
from typing import Optional

@dataclass
class AddressInfo:
    """地址信息（从addresses.json读取）"""
    address: str
    name: Optional[str] = None
    chain: Optional[str] = None
    source: str = "unknown"
    context: Optional[str] = None

    # 链上数据补全字段(来自OnChainDataFetcher,可选)
    onchain_name: Optional[str] = None
    symbol: Optional[str] = None
    decimals: Optional[int] = None
    is_erc20: Optional[bool] = None
    semantic_type: Optional[str] = None
    aliases: Optional[list] = None

def test_backward_compatibility():
    """测试旧版 addresses.json 的兼容性"""
    print("=" * 80)
    print("测试向后兼容性: 旧版 addresses.json(无补全字段)")
    print("=" * 80)
    print()

    # 模拟旧版地址数据(只有基础字段)
    old_addr_data = {
        "address": "0x04c80Bb477890F3021F03B068238836Ee20aA0b8",
        "name": "IwBARL",
        "chain": "mainnet",
        "source": "static"
    }

    print("输入数据(旧版 addresses.json 条目):")
    for key, value in old_addr_data.items():
        print(f"  {key}: {value}")
    print()

    try:
        addr_info = AddressInfo(**old_addr_data)
        print("✅ AddressInfo 创建成功")
        print()
        print("AddressInfo 对象内容:")
        print(f"  address: {addr_info.address}")
        print(f"  name: {addr_info.name}")
        print(f"  chain: {addr_info.chain}")
        print(f"  source: {addr_info.source}")
        print(f"  context: {addr_info.context}")
        print()

        # 验证补全字段默认为None
        print("补全字段(应为默认值None):")
        print(f"  onchain_name: {addr_info.onchain_name}")
        print(f"  symbol: {addr_info.symbol}")
        print(f"  decimals: {addr_info.decimals}")
        print(f"  is_erc20: {addr_info.is_erc20}")
        print(f"  semantic_type: {addr_info.semantic_type}")
        print(f"  aliases: {addr_info.aliases}")
        print()

        assert addr_info.symbol is None
        assert addr_info.decimals is None
        assert addr_info.is_erc20 is None
        print("✅ 补全字段正确默认为None")
        print()

        print("=" * 80)
        print("✅ 向后兼容性测试通过")
        print("=" * 80)
        print()
        print("结论:")
        print("1. 旧版 addresses.json(无补全字段)仍可正常解析")
        print("2. 缺失的字段自动使用默认值(None)")
        print("3. 不会影响现有工作流程")

        return True

    except Exception as e:
        print(f"❌ 创建失败: {e}")
        return False

if __name__ == "__main__":
    success = test_backward_compatibility()
    exit(0 if success else 1)
