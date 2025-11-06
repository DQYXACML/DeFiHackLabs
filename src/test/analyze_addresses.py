#!/usr/bin/env python3
"""
分析提取的合约地址数据

功能:
- 统计各链上的合约数量
- 列出所有已验证和未验证的合约
- 生成地址报告
"""

import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List

def analyze_addresses(base_dir: Path):
    """分析所有提取的地址数据"""

    print("=" * 80)
    print("DeFi攻击合约地址分析报告")
    print("=" * 80)

    # 统计数据
    total_scripts = 0
    total_addresses = 0
    chain_stats = defaultdict(int)
    source_stats = defaultdict(int)
    all_addresses = []

    # 遍历所有目录
    for date_dir in sorted(base_dir.iterdir()):
        if not date_dir.is_dir():
            continue

        for script_dir in sorted(date_dir.iterdir()):
            if not script_dir.is_dir():
                continue

            addresses_file = script_dir / 'addresses.json'
            if not addresses_file.exists():
                continue

            total_scripts += 1

            # 读取地址数据
            with open(addresses_file, 'r') as f:
                addresses = json.load(f)

            total_addresses += len(addresses)

            for addr in addresses:
                chain = addr.get('chain', 'unknown')
                source = addr.get('source', 'unknown')

                chain_stats[chain] += 1
                source_stats[source] += 1

                all_addresses.append({
                    'script': f"{date_dir.name}/{script_dir.name}",
                    **addr
                })

    # 打印统计
    print(f"\n总攻击脚本数: {total_scripts}")
    print(f"总地址数: {total_addresses}")
    print(f"平均每个脚本: {total_addresses/total_scripts:.1f} 个地址")

    print("\n## 按链分类:")
    for chain, count in sorted(chain_stats.items(), key=lambda x: -x[1]):
        percentage = count / total_addresses * 100
        print(f"  {chain:15} : {count:4} ({percentage:5.1f}%)")

    print("\n## 按提取方式分类:")
    for source, count in sorted(source_stats.items(), key=lambda x: -x[1]):
        percentage = count / total_addresses * 100
        desc = {
            'comment': '从注释中提取',
            'static': '从代码常量提取',
            'dynamic': '从执行trace提取'
        }.get(source, source)
        print(f"  {desc:20} : {count:4} ({percentage:5.1f}%)")

    # 按脚本列出地址
    print("\n## 各攻击脚本提取的地址:")
    current_script = None
    for addr in sorted(all_addresses, key=lambda x: x['script']):
        script = addr['script']
        if script != current_script:
            current_script = script
            print(f"\n### {script}")

        name = addr.get('name', 'Unknown')
        address = addr['address']
        chain = addr.get('chain', 'unknown')
        source = addr.get('source', 'unknown')

        print(f"  - [{name:20}] {address} ({chain}, {source})")

    # 保存完整报告
    report_file = base_dir / 'address_report.json'
    with open(report_file, 'w') as f:
        json.dump({
            'summary': {
                'total_scripts': total_scripts,
                'total_addresses': total_addresses,
                'chain_stats': dict(chain_stats),
                'source_stats': dict(source_stats)
            },
            'addresses': all_addresses
        }, f, indent=2)

    print(f"\n完整报告已保存到: {report_file}")
    print("=" * 80)


def main():
    base_dir = Path('contract_sources')

    if not base_dir.exists():
        print(f"错误: {base_dir} 目录不存在")
        print("请先运行 extract_contracts.py")
        return

    analyze_addresses(base_dir)


if __name__ == '__main__':
    main()
