#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存储查询诊断工具

用于诊断为什么不变量检测结果显示 "inf%"
检查：
1. 合约是否部署到Anvil
2. 存储槽是否有值
3. 地址格式是否正确
"""

import subprocess
import json
import sys
from pathlib import Path
from typing import Optional


def check_contract_deployed(address: str, rpc_url: str) -> bool:
    """检查合约是否部署"""
    result = subprocess.run(
        ['cast', 'code', address, '--rpc-url', rpc_url],
        capture_output=True, text=True, timeout=10
    )
    code = result.stdout.strip()
    deployed = code != "0x" and len(code) > 4
    status = '✓ 已部署' if deployed else '✗ 未部署'
    print(f"  合约 {address[:10]}...{address[-6:]}: {status} (代码长度: {len(code)})")
    return deployed


def check_storage_slot(address: str, slot: int, rpc_url: str) -> Optional[int]:
    """检查存储槽值"""
    result = subprocess.run(
        ['cast', 'storage', address, str(slot), '--rpc-url', rpc_url],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        value = result.stdout.strip()
        value_int = int(value, 16) if value else 0
        if value_int == 0:
            print(f"  存储槽 {slot}: {value} (十进制: 0) ⚠️")
        else:
            print(f"  存储槽 {slot}: {value} (十进制: {value_int:,}) ✓")
        return value_int
    else:
        print(f"  存储槽 {slot}: ✗ 查询失败 - {result.stderr}")
        return None


def check_balance(address: str, rpc_url: str) -> Optional[int]:
    """检查合约余额"""
    result = subprocess.run(
        ['cast', 'balance', address, '--rpc-url', rpc_url],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        balance = int(result.stdout.strip())
        if balance == 0:
            print(f"  余额: 0 wei ⚠️")
        else:
            print(f"  余额: {balance:,} wei ✓")
        return balance
    else:
        print(f"  余额查询失败: {result.stderr}")
        return None


def diagnose_event(event_name: str, year_month: str, rpc_url: str = "http://127.0.0.1:8545"):
    """诊断单个攻击事件"""
    print(f"\n{'='*70}")
    print(f"诊断: {year_month}/{event_name}")
    print(f"{'='*70}\n")

    # 构建路径
    base_dir = Path(__file__).parent.parent.parent
    inv_file = base_dir / "extracted_contracts" / year_month / event_name / "invariants.json"

    if not inv_file.exists():
        print(f"❌ 不变量文件不存在: {inv_file}")
        return False

    # 加载不变量
    with open(inv_file, 'r') as f:
        inv_data = json.load(f)

    storage_invs = inv_data.get('storage_invariants', [])
    if not storage_invs:
        print("⚠️  没有存储级不变量")
        return True

    print(f"📋 共有 {len(storage_invs)} 个存储不变量\n")

    # 检查前3个不变量的合约状态
    issues = []

    for i, inv in enumerate(storage_invs[:3], 1):
        print(f"--- 不变量 {i}: {inv.get('id')} ({inv.get('type')}) ---")

        slots = inv.get('slots', {})
        contracts_to_check = set()

        # 收集需要检查的合约
        if 'totalSupply_contract' in slots:
            contracts_to_check.add(slots['totalSupply_contract'])
        if 'reserves_contract' in slots:
            contracts_to_check.add(slots['reserves_contract'])
        if 'contract' in slots:
            contracts_to_check.add(slots['contract'])

        # 检查每个合约
        for contract in contracts_to_check:
            print(f"\n合约: {contract}")

            # 1. 检查部署状态
            deployed = check_contract_deployed(contract, rpc_url)
            if not deployed:
                issues.append(f"合约未部署: {contract}")

            # 2. 检查存储槽
            if 'totalSupply_slot' in slots and slots.get('totalSupply_contract') == contract:
                slot_num = int(slots['totalSupply_slot'])
                value = check_storage_slot(contract, slot_num, rpc_url)
                if value == 0:
                    issues.append(f"存储槽值为0: {contract}[{slot_num}]")
            elif 'monitored_slot' in slots and slots.get('contract') == contract:
                slot_num = int(slots['monitored_slot'])
                value = check_storage_slot(contract, slot_num, rpc_url)
                if value == 0:
                    issues.append(f"存储槽值为0: {contract}[{slot_num}]")

            # 3. 检查余额
            balance = check_balance(contract, rpc_url)

        print()

    # 诊断总结
    print(f"\n{'='*70}")
    print("诊断总结:")
    print(f"{'='*70}")

    if not issues:
        print("✅ 所有检查通过，存储数据看起来正常")
        return True
    else:
        print(f"⚠️  发现 {len(issues)} 个问题:\n")
        for issue in issues:
            print(f"  • {issue}")

        print("\n可能的解决方案:")
        print("  1. 确保 attack_state.json 包含完整的合约状态和存储数据")
        print("  2. 检查 deploy_to_anvil.py 是否成功执行")
        print("  3. 验证 Anvil 是否正确启动并运行")
        print("  4. 确认地址格式统一（建议全部使用小写）")

        return False


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='诊断存储查询问题')
    parser.add_argument('--event-name', help='攻击事件名称（如 MIMSpell2_exp）')
    parser.add_argument('--year-month', default='2024-01', help='年月目录（默认 2024-01）')
    parser.add_argument('--rpc-url', default='http://127.0.0.1:8545', help='Anvil RPC URL')

    args = parser.parse_args()

    if args.event_name:
        # 诊断单个事件
        success = diagnose_event(args.event_name, args.year_month, args.rpc_url)
        sys.exit(0 if success else 1)
    else:
        # 自动选择第一个可用事件进行诊断
        base_dir = Path(__file__).parent.parent.parent
        extracted_dir = base_dir / "extracted_contracts" / args.year_month

        if not extracted_dir.exists():
            print(f"❌ 目录不存在: {extracted_dir}")
            sys.exit(1)

        # 找到第一个有invariants.json的事件
        for event_dir in extracted_dir.iterdir():
            if event_dir.is_dir():
                inv_file = event_dir / "invariants.json"
                if inv_file.exists():
                    event_name = event_dir.name
                    print(f"自动选择: {event_name}")
                    success = diagnose_event(event_name, args.year_month, args.rpc_url)
                    sys.exit(0 if success else 1)

        print(f"❌ 在 {args.year_month} 目录下未找到任何有 invariants.json 的事件")
        sys.exit(1)


if __name__ == '__main__':
    main()
