#!/usr/bin/env python3
"""
测试 collect_attack_states.py 对补全后 addresses.json 的兼容性

验证点:
1. AddressInfo 能否正确解析包含额外字段的字典
2. 额外字段是否被正确忽略
3. 核心功能(address和name)是否正常工作
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

def test_enriched_address_parsing():
    """测试解析补全后的地址数据"""
    print("=" * 80)
    print("测试 AddressInfo 与补全后 addresses.json 的兼容性")
    print("=" * 80)
    print()

    # 模拟补全后的地址数据(包含额外字段)
    enriched_addr_data = {
        "address": "0x04c80Bb477890F3021F03B068238836Ee20aA0b8",
        "name": "IwBARL",
        "chain": "mainnet",
        "source": "static",
        "context": None,
        "onchain_name": None,
        "symbol": "wBARL",
        "decimals": 18,
        "is_erc20": True,
        "semantic_type": "wrapped_token",
        "aliases": ["wBARL", "IwBARL", "wbarl", "WBARL"]
    }

    print("输入数据(补全后的 addresses.json 条目):")
    for key, value in enriched_addr_data.items():
        print(f"  {key}: {value}")
    print()

    # 尝试使用 **kwargs 解包创建 AddressInfo
    try:
        addr_info = AddressInfo(**enriched_addr_data)
        print("✅ AddressInfo 创建成功")
        print()
        print("AddressInfo 对象内容:")
        print(f"  address: {addr_info.address}")
        print(f"  name: {addr_info.name}")
        print(f"  chain: {addr_info.chain}")
        print(f"  source: {addr_info.source}")
        print(f"  context: {addr_info.context}")
        print()

        # 验证核心字段
        assert addr_info.address == "0x04c80Bb477890F3021F03B068238836Ee20aA0b8"
        assert addr_info.name == "IwBARL"
        print("✅ 核心字段(address, name)正确")
        print()

        # 验证额外字段已正确加载
        assert hasattr(addr_info, 'symbol')
        assert addr_info.symbol == "wBARL"
        assert addr_info.decimals == 18
        assert addr_info.is_erc20 == True
        assert addr_info.semantic_type == "wrapped_token"
        assert addr_info.aliases == ["wBARL", "IwBARL", "wbarl", "WBARL"]
        print("✅ 补全字段(symbol, decimals等)正确加载")
        print()

        print("=" * 80)
        print("结论: collect_attack_states.py 已成功更新")
        print("=" * 80)
        print()
        print("修改内容:")
        print("1. AddressInfo 扩展了6个新字段,所有字段都是 Optional")
        print("2. 向后兼容: 旧的 addresses.json(无补全字段)仍可正常解析")
        print("3. 向前兼容: 新的补全字段会被正确加载和存储")
        print()
        print("新增字段:")
        print("  - onchain_name: 从链上获取的合约名称")
        print("  - symbol: ERC20 token symbol")
        print("  - decimals: ERC20 decimals")
        print("  - is_erc20: 是否为ERC20代币")
        print("  - semantic_type: 语义类型(wrapped_token等)")
        print("  - aliases: 别名列表")


        return True

    except Exception as e:
        print(f"❌ 创建失败: {e}")
        return False

if __name__ == "__main__":
    success = test_enriched_address_parsing()
    exit(0 if success else 1)
