#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存储对比工具

功能：
- 批量查询Anvil上的存储槽
- 对比before/after状态
- 计算变化率和绝对变化
- 处理ERC20余额变化
"""

import json
import logging
import requests
import subprocess
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class StorageSlotChange:
    """存储槽变化数据"""
    contract: str
    slot: int
    value_before: int
    value_after: int
    change_abs: int
    change_rate: float

    def to_dict(self) -> Dict:
        return {
            'contract': self.contract,
            'slot': self.slot,
            'before': self.value_before,
            'after': self.value_after,
            'change_abs': self.change_abs,
            'change_rate': self.change_rate,
            'change_pct': f"{self.change_rate * 100:.2f}%"
        }


class StorageComparator:
    """存储对比器"""

    def __init__(self, rpc_url: str = "http://127.0.0.1:8545"):
        """
        初始化存储对比器

        Args:
            rpc_url: Anvil RPC地址
        """
        self.rpc_url = rpc_url

    def capture_snapshot(
        self,
        contracts_and_slots: List[Tuple[str, int]],
        include_balances: bool = True
    ) -> Dict:
        """
        捕获存储快照

        Args:
            contracts_and_slots: [(contract_address, slot_number), ...]
            include_balances: 是否包含合约余额

        Returns:
            {
                'storage': {
                    'contract_address': {
                        slot: value,
                        ...
                    },
                    ...
                },
                'balances': {
                    'contract_address': balance_wei,
                    ...
                }
            }
        """
        snapshot = {
            'storage': {},
            'balances': {}
        }

        # 批量查询存储槽
        if contracts_and_slots:
            storage_data = self._query_storage_batch(contracts_and_slots)
            snapshot['storage'] = storage_data

        # 查询余额
        if include_balances:
            unique_contracts = set(addr for addr, _ in contracts_and_slots)
            balances = self._query_balances_batch(list(unique_contracts))
            snapshot['balances'] = balances

        return snapshot

    def compare_snapshots(
        self,
        before: Dict,
        after: Dict
    ) -> Dict:
        """
        对比两个快照的存储变化

        Args:
            before: 之前的快照
            after: 之后的快照

        Returns:
            {
                'contract_address': {
                    slot: {
                        'before': value,
                        'after': value,
                        'change_abs': abs_change,
                        'change_rate': rate,
                        'change_pct': 'XX.XX%'
                    },
                    ...
                },
                'balances': {
                    'contract_address': {
                        'before': balance,
                        'after': balance,
                        'change_abs': change,
                        'change_rate': rate
                    }
                }
            }
        """
        changes = {}

        # 对比存储槽变化
        storage_before = before.get('storage', {})
        storage_after = after.get('storage', {})

        all_contracts = set(storage_before.keys()) | set(storage_after.keys())

        for contract in all_contracts:
            contract_changes = {}
            slots_before = storage_before.get(contract, {})
            slots_after = storage_after.get(contract, {})

            all_slots = set(slots_before.keys()) | set(slots_after.keys())

            for slot in all_slots:
                value_before = slots_before.get(slot, 0)
                value_after = slots_after.get(slot, 0)

                change_abs = value_after - value_before

                # 计算变化率
                if value_before > 0:
                    change_rate = abs(change_abs) / value_before
                elif value_after > 0:
                    change_rate = float('inf')
                else:
                    change_rate = 0.0

                contract_changes[slot] = {
                    'before': value_before,
                    'after': value_after,
                    'change_abs': change_abs,
                    'change_rate': change_rate,
                    'change_pct': f"{change_rate * 100:.2f}%" if change_rate != float('inf') else 'INF'
                }

            if contract_changes:
                changes[contract] = contract_changes

        # 对比余额变化
        balances_before = before.get('balances', {})
        balances_after = after.get('balances', {})

        balance_changes = {}
        all_balance_addrs = set(balances_before.keys()) | set(balances_after.keys())

        for addr in all_balance_addrs:
            bal_before = balances_before.get(addr, 0)
            bal_after = balances_after.get(addr, 0)

            change_abs = bal_after - bal_before

            if bal_before > 0:
                change_rate = abs(change_abs) / bal_before
            elif bal_after > 0:
                change_rate = float('inf')
            else:
                change_rate = 0.0

            balance_changes[addr] = {
                'before': bal_before,
                'after': bal_after,
                'change_abs': change_abs,
                'change_rate': change_rate
            }

        changes['balances'] = balance_changes

        return changes

    def extract_slots_from_invariants(self, invariants: List[Dict]) -> List[Tuple[str, int]]:
        """
        从不变量规则中提取需要监控的存储槽

        Args:
            invariants: 不变量列表

        Returns:
            [(contract_address, slot_number), ...]
        """
        slots = set()

        for inv in invariants:
            inv_slots = inv.get('slots', {})

            # 提取totalSupply槽
            if 'totalSupply_slot' in inv_slots and 'totalSupply_contract' in inv_slots:
                contract = inv_slots['totalSupply_contract']
                slot = int(inv_slots['totalSupply_slot'])
                slots.add((contract, slot))

            # 提取reserves槽
            if 'reserves_slot' in inv_slots and 'reserves_contract' in inv_slots:
                contract = inv_slots['reserves_contract']
                slot = int(inv_slots['reserves_slot'])
                slots.add((contract, slot))

            # 提取通用监控槽
            if 'monitored_slot' in inv_slots:
                contract = inv_slots.get('contract') or inv.get('contracts', [None])[0]
                if contract:
                    slot = int(inv_slots['monitored_slot'])
                    slots.add((contract, slot))

            # 提取contracts列表中的所有合约（用于余额查询）
            contracts = inv.get('contracts', [])
            for contract in contracts:
                # 默认查询slot 2（ERC20 totalSupply）
                slots.add((contract, 2))

        return list(slots)

    # ==================== 内部方法 ====================

    def _query_storage_batch(
        self,
        contracts_and_slots: List[Tuple[str, int]]
    ) -> Dict[str, Dict[int, int]]:
        """
        批量查询存储槽（使用JSON-RPC批量请求）

        Args:
            contracts_and_slots: [(contract, slot), ...]

        Returns:
            {contract: {slot: value, ...}, ...}
        """
        if not contracts_and_slots:
            return {}

        # 方法1: 使用RPC批量请求（更快）
        try:
            return self._query_via_rpc_batch(contracts_and_slots)
        except Exception as e:
            logger.warning(f"RPC批量查询失败，回退到cast命令: {e}")

        # 方法2: 使用cast命令（更可靠但慢）
        return self._query_via_cast(contracts_and_slots)

    def _query_via_rpc_batch(
        self,
        contracts_and_slots: List[Tuple[str, int]]
    ) -> Dict[str, Dict[int, int]]:
        """通过RPC批量请求查询存储"""
        batch_requests = []

        for i, (contract, slot) in enumerate(contracts_and_slots):
            batch_requests.append({
                'jsonrpc': '2.0',
                'method': 'eth_getStorageAt',
                'params': [contract, hex(slot), 'latest'],
                'id': i
            })

        # 发送批量请求
        response = requests.post(
            self.rpc_url,
            json=batch_requests,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )

        if response.status_code != 200:
            raise Exception(f"RPC请求失败: {response.status_code}")

        results = response.json()

        # 解析结果
        storage_data = {}
        for i, (contract, slot) in enumerate(contracts_and_slots):
            if isinstance(results, list):
                result_item = results[i]
            else:
                result_item = results

            if 'result' in result_item:
                value_hex = result_item['result']
                value = int(value_hex, 16) if value_hex else 0

                if contract not in storage_data:
                    storage_data[contract] = {}

                storage_data[contract][slot] = value
            else:
                logger.warning(f"获取存储槽失败: {contract}[{slot}], 错误: {result_item.get('error')}")

        return storage_data

    def _query_via_cast(
        self,
        contracts_and_slots: List[Tuple[str, int]]
    ) -> Dict[str, Dict[int, int]]:
        """通过cast命令逐个查询存储"""
        storage_data = {}

        for contract, slot in contracts_and_slots:
            try:
                result = subprocess.run(
                    ['cast', 'storage', contract, str(slot), '--rpc-url', self.rpc_url],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    value_hex = result.stdout.strip()
                    value = int(value_hex, 16) if value_hex else 0

                    if contract not in storage_data:
                        storage_data[contract] = {}

                    storage_data[contract][slot] = value
                else:
                    logger.warning(f"查询存储槽失败: {contract}[{slot}]")

            except Exception as e:
                logger.error(f"查询存储槽异常: {contract}[{slot}], {e}")

        return storage_data

    def _query_balances_batch(self, contracts: List[str]) -> Dict[str, int]:
        """批量查询合约余额"""
        if not contracts:
            return {}

        # 使用RPC批量请求
        batch_requests = []

        for i, contract in enumerate(contracts):
            batch_requests.append({
                'jsonrpc': '2.0',
                'method': 'eth_getBalance',
                'params': [contract, 'latest'],
                'id': i
            })

        try:
            response = requests.post(
                self.rpc_url,
                json=batch_requests,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )

            if response.status_code != 200:
                raise Exception(f"RPC请求失败: {response.status_code}")

            results = response.json()

            balances = {}
            for i, contract in enumerate(contracts):
                if isinstance(results, list):
                    result_item = results[i]
                else:
                    result_item = results

                if 'result' in result_item:
                    balance_hex = result_item['result']
                    balance = int(balance_hex, 16) if balance_hex else 0
                    balances[contract] = balance

            return balances

        except Exception as e:
            logger.warning(f"批量查询余额失败: {e}，回退到逐个查询")
            return self._query_balances_individual(contracts)

    def _query_balances_individual(self, contracts: List[str]) -> Dict[str, int]:
        """逐个查询余额（回退方案）"""
        balances = {}

        for contract in contracts:
            try:
                result = subprocess.run(
                    ['cast', 'balance', contract, '--rpc-url', self.rpc_url],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    balance = int(result.stdout.strip())
                    balances[contract] = balance

            except Exception as e:
                logger.error(f"查询余额异常: {contract}, {e}")

        return balances


if __name__ == '__main__':
    # 测试示例
    comparator = StorageComparator(rpc_url="http://127.0.0.1:8545")

    # 测试提取存储槽
    test_invariants = [
        {
            'id': 'SINV_001',
            'type': 'share_price_stability',
            'slots': {
                'totalSupply_contract': '0x1234567890123456789012345678901234567890',
                'totalSupply_slot': '2',
                'reserves_contract': '0xabcdefabcdefabcdefabcdefabcdefabcdefabcd'
            },
            'contracts': [
                '0x1234567890123456789012345678901234567890',
                '0xabcdefabcdefabcdefabcdefabcdefabcdefabcd'
            ]
        }
    ]

    slots = comparator.extract_slots_from_invariants(test_invariants)
    print(f"提取到的存储槽: {slots}")

    # 注意: 以下测试需要Anvil运行
    # snapshot_before = comparator.capture_snapshot(slots)
    # print(f"快照: {json.dumps(snapshot_before, indent=2)}")
