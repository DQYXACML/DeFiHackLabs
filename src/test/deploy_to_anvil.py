#!/usr/bin/env python3
"""
部署攻击状态到本地 Anvil 节点

使用 anvil 的 RPC 方法直接设置状态
"""

import json
import sys
import argparse
from pathlib import Path
from web3 import Web3

def deploy_to_anvil(state_file: Path, rpc_url: str = "http://localhost:8545"):
    """部署状态到 anvil"""
    
    # 连接到 anvil
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print(f"❌ 无法连接到 {rpc_url}")
        return False
    
    print(f"✓ 已连接到 {rpc_url}")
    
    # 读取状态文件
    with open(state_file, 'r') as f:
        state = json.load(f)
    
    metadata = state['metadata']
    addresses = state['addresses']
    
    print(f"\n部署事件状态:")
    print(f"  链: {metadata['chain']}")
    print(f"  区块: {metadata['block_number']}")
    print(f"  地址数量: {metadata['total_addresses']}")
    print()
    
    # 部署每个地址的状态
    for addr, data in addresses.items():
        print(f"处理 {addr}...")
        
        # 1. 设置代码
        if data['code'] and data['code'] != '0x':
            result = w3.provider.make_request('anvil_setCode', [addr, data['code']])
            print(f"  ✓ 设置代码: {len(data['code'])//2} bytes")
        
        # 2. 设置余额
        balance_hex = hex(int(data['balance_wei']))
        w3.provider.make_request('anvil_setBalance', [addr, balance_hex])
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
    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='部署攻击状态到本地 Anvil 节点',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--state-file',
        type=Path,
        required=True,
        help='攻击状态文件 (attack_state.json)'
    )

    parser.add_argument(
        '--rpc-url',
        default='http://localhost:8545',
        help='Anvil RPC URL (默认: http://localhost:8545)'
    )

    args = parser.parse_args()

    if not args.state_file.exists():
        print(f"❌ 文件不存在: {args.state_file}")
        sys.exit(1)

    try:
        success = deploy_to_anvil(args.state_file, args.rpc_url)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ 部署失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
