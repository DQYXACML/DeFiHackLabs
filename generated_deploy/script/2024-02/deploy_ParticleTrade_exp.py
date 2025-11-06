#!/usr/bin/env python3
"""
部署 ParticleTrade_exp 攻击状态到本地 Anvil

事件信息:
- 链: mainnet
- 区块: 19231445
- 时间戳: 1707977315
- 合约数量: 9

生成时间: 2025-11-03T14:11:56.123113
"""

import json
import sys
from pathlib import Path
from web3 import Web3

def deploy_to_anvil(rpc_url: str = "http://localhost:8545"):
    """部署状态到 anvil"""

    # 连接到 anvil
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print(f"❌ 无法连接到 {rpc_url}")
        return False

    print(f"✓ 已连接到 {rpc_url}")
    print(f"\n部署 ParticleTrade_exp 攻击状态")
    print(f"  链: mainnet")
    print(f"  区块: 19231445")
    print(f"  地址数量: 9")
    print()

    # 读取状态文件
    state_file = Path(__file__).parent.parent.parent.parent / "extracted_contracts" / "2024-02" / "ParticleTrade_exp" / "attack_state.json"
    if not state_file.exists():
        print(f"❌ 状态文件不存在: {state_file}")
        return False

    with open(state_file, 'r') as f:
        state = json.load(f)

    addresses = state['addresses']

    # 部署每个地址的状态
    for addr, data in addresses.items():
        print(f"处理 {addr}...")

        # 1. 设置代码
        if data['code'] and data['code'] != '0x':
            w3.provider.make_request('anvil_setCode', [addr, data['code']])
            print(f"  ✓ 设置代码: {len(data['code'])//2} bytes")

        # 2. 设置余额
        balance_hex = hex(int(data['balance_wei']))
        w3.provider.make_request('anvil_setBalance', [addr, balance_hex])
        if data['balance_wei'] != "0":
            print(f"  ✓ 设置余额: {data['balance_wei']} wei")

        # 3. 设置 storage
        if data['storage']:
            for slot, value in data['storage'].items():
                slot_hex = hex(int(slot))
                if not value.startswith('0x'):
                    value = '0x' + value
                w3.provider.make_request('anvil_setStorageAt', [addr, slot_hex, value])
            print(f"  ✓ 设置 storage: {len(data['storage'])} slots")

        # 4. 设置 nonce
        if data['nonce'] > 0:
            nonce_hex = hex(data['nonce'])
            w3.provider.make_request('anvil_setNonce', [addr, nonce_hex])
            print(f"  ✓ 设置 nonce: {data['nonce']}")

    print(f"\n✅ 部署完成！共 {len(addresses)} 个地址")

    # 验证部署
    print("\n验证部署:")
    sample_addrs = list(addresses.keys())[:3]
    for addr in sample_addrs:
        addr_checksum = w3.to_checksum_address(addr)
        balance = w3.eth.get_balance(addr_checksum)
        code_size = len(w3.eth.get_code(addr_checksum))
        print(f"  {addr_checksum}: balance={balance} wei, code={code_size} bytes")

    return True

if __name__ == '__main__':
    rpc_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8545"
    success = deploy_to_anvil(rpc_url)
    sys.exit(0 if success else 1)
