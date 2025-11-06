#!/usr/bin/env python3
"""
集成示例：在collect_attack_states.py中使用增强版存储收集

展示如何收集包含mapping和动态数组的完整状态
"""

import sys
from pathlib import Path
from web3 import Web3

# 添加当前目录到path
sys.path.insert(0, str(Path(__file__).parent))

from enhanced_state_collector import EnhancedStorageCollector


class IntegratedStateCollector:
    """
    集成的状态收集器

    结合原有的简单扫描和新的增强收集功能
    """

    def __init__(self, w3: Web3):
        self.w3 = w3
        self.enhanced_collector = EnhancedStorageCollector(w3)

    def collect_attack_state(
        self,
        contract_address: str,
        block_number: int,
        attack_tx_hash: str,
        protocol_config: dict
    ) -> dict:
        """
        收集攻击状态的完整方法

        Args:
            contract_address: 目标合约地址
            block_number: fork区块号
            attack_tx_hash: 攻击交易哈希
            protocol_config: 协议特定配置，定义已知的mapping位置

        Returns:
            完整的状态数据
        """

        # 1. 从攻击交易日志提取相关地址
        print(f"  [1/4] 从攻击交易提取相关地址...")
        related_addresses = self.enhanced_collector.extract_addresses_from_logs(
            attack_tx_hash
        )
        print(f"      找到 {len(related_addresses)} 个相关地址")

        # 2. 构建mapping查询配置
        # 根据协议配置，将提取的地址映射到对应的mapping slot
        known_mappings = {}
        if 'mapping_slots' in protocol_config:
            for slot_info in protocol_config['mapping_slots']:
                slot = slot_info['slot']
                mapping_type = slot_info.get('type', 'address')

                if mapping_type == 'address':
                    # 使用从日志提取的地址
                    known_mappings[slot] = list(related_addresses)
                elif mapping_type == 'uint256':
                    # 使用配置中指定的key
                    known_mappings[slot] = slot_info.get('keys', [])

        # 3. 综合收集存储
        print(f"  [2/4] 收集合约存储...")
        storage = self.enhanced_collector.collect_storage_comprehensive(
            contract_address=contract_address,
            block_number=block_number,
            attack_tx_hash=attack_tx_hash,
            known_mappings=known_mappings,
            max_sequential_slots=protocol_config.get('max_sequential_slots', 100)
        )

        # 4. 收集其他基础数据
        print(f"  [3/4] 收集基础数据（余额、代码等）...")
        address = Web3.to_checksum_address(contract_address)
        balance = self.w3.eth.get_balance(address, block_number)
        nonce = self.w3.eth.get_transaction_count(address, block_number)
        code = self.w3.eth.get_code(address, block_number)

        # 5. 构建完整状态
        print(f"  [4/4] 构建状态快照...")
        state = {
            'address': address,
            'balance_wei': str(balance),
            'balance_eth': str(self.w3.from_wei(balance, 'ether')),
            'nonce': nonce,
            'code': code.hex(),
            'code_size': len(code),
            'is_contract': len(code) > 0,
            'storage': storage,
            'storage_count': len(storage),
            'related_addresses': list(related_addresses),
            'collection_metadata': {
                'attack_tx': attack_tx_hash,
                'block_number': block_number,
                'used_trace_analysis': True,
                'used_mapping_collection': len(known_mappings) > 0
            }
        }

        return state


# ============================================================================
# 协议配置示例
# ============================================================================

# Lodestar 协议配置示例
LODESTAR_CONFIG = {
    'protocol': 'Lodestar',
    'max_sequential_slots': 100,
    'mapping_slots': [
        {
            'slot': 5,
            'name': 'accountTokens',  # mapping(address => uint256)
            'type': 'address',
            'description': 'User token balances'
        },
        {
            'slot': 6,
            'name': 'markets',  # mapping(address => Market)
            'type': 'address',
            'description': 'Market configurations'
        },
        {
            'slot': 10,
            'name': 'borrowBalance',  # mapping(address => BorrowSnapshot)
            'type': 'address',
            'description': 'User borrow balances'
        }
    ]
}

# ERC20 通用配置
ERC20_CONFIG = {
    'protocol': 'ERC20',
    'max_sequential_slots': 20,
    'mapping_slots': [
        {
            'slot': 0,
            'name': 'balances',  # mapping(address => uint256)
            'type': 'address',
            'description': 'Token balances'
        },
        {
            'slot': 1,
            'name': 'allowances',  # mapping(address => mapping(address => uint256))
            'type': 'address',
            'description': 'Token allowances (nested mapping需要特殊处理)'
        }
    ]
}

# Uniswap V2 Pair 配置
UNISWAP_V2_PAIR_CONFIG = {
    'protocol': 'UniswapV2Pair',
    'max_sequential_slots': 50,
    'mapping_slots': [
        # Uniswap V2 Pair主要用简单变量，但如果有ERC20继承
        {
            'slot': 3,
            'name': 'balanceOf',
            'type': 'address',
            'description': 'LP token balances'
        }
    ]
}


# ============================================================================
# 使用示例
# ============================================================================

def main():
    """完整使用示例"""

    # 1. 连接到节点（使用fork URL）
    w3 = Web3(Web3.HTTPProvider('https://arb1.arbitrum.io/rpc'))
    # 或使用本地节点
    # w3 = Web3(Web3.HTTPProvider('http://localhost:8545'))

    collector = IntegratedStateCollector(w3)

    # 2. 收集Lodestar攻击状态示例
    print("收集 Lodestar 攻击状态...")
    print("=" * 80)

    lodestar_state = collector.collect_attack_state(
        contract_address='0x1ca530f02DD0487cef4943c674342c5aEa08922F',  # plvGLP
        block_number=45121903,
        attack_tx_hash='0xb60d4817366f95b89d5396d7b26fc0fd42e4c10e9df20ec1f572479c2c61207a',
        protocol_config=LODESTAR_CONFIG
    )

    print("\n状态收集完成!")
    print(f"存储条目数: {lodestar_state['storage_count']}")
    print(f"相关地址数: {len(lodestar_state['related_addresses'])}")

    # 3. 保存到文件
    import json
    output_path = Path('lodestar_attack_state_enhanced.json')
    with open(output_path, 'w') as f:
        json.dump(lodestar_state, f, indent=2)

    print(f"\n已保存到: {output_path}")


# ============================================================================
# 如何集成到现有的 collect_attack_states.py
# ============================================================================
"""
在 collect_attack_states.py 的 StateCollector 类中：

1. 修改 __init__ 方法：
   def __init__(self, rpc_manager, storage_depth=DEFAULT_STORAGE_DEPTH):
       self.rpc_manager = rpc_manager
       self.storage_depth = storage_depth
       # 新增：创建增强收集器
       self.enhanced_collector = None  # 延迟初始化

2. 修改 _collect_address_state 方法：
   def _collect_address_state(self, w3, address, block_number,
                              attack_tx_hash=None, protocol_config=None):
       # ... 现有代码 ...

       # 存储数据收集
       if is_contract:
           if attack_tx_hash and protocol_config:
               # 使用增强收集器
               if not self.enhanced_collector:
                   from enhanced_state_collector import EnhancedStorageCollector
                   self.enhanced_collector = EnhancedStorageCollector(w3)

               storage = self.enhanced_collector.collect_storage_comprehensive(
                   contract_address=address,
                   block_number=block_number,
                   attack_tx_hash=attack_tx_hash,
                   known_mappings=protocol_config.get('mapping_slots'),
                   max_sequential_slots=self.storage_depth
               )
           else:
               # 使用原有的简单扫描
               storage = self._collect_storage(w3, address, block_number)

       # ... 其余代码 ...

3. 添加协议配置文件：
   创建 protocol_configs.py，定义各个协议的mapping配置

4. 在主收集逻辑中传入配置：
   # 根据事件名称选择协议配置
   if 'Lodestar' in event_name:
       protocol_config = LODESTAR_CONFIG
   elif 'ERC20' in event_name:
       protocol_config = ERC20_CONFIG
   else:
       protocol_config = None
"""


if __name__ == '__main__':
    main()
