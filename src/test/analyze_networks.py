#!/usr/bin/env python3
"""
分析所有攻击脚本涉及的区块链网络及其API配置

功能:
- 统计各个网络的攻击脚本数量
- 识别每个网络应使用的API Key
- 生成API Key申请链接
"""

import re
from pathlib import Path
from collections import defaultdict
import json

# 网络到API服务的映射
NETWORK_TO_API = {
    # Ethereum生态
    "mainnet": {
        "api_service": "Etherscan",
        "api_url": "https://api.etherscan.io/v2/api",
        "api_key_url": "https://etherscan.io/myapikey",
        "chainid": 1,
        "uses_etherscan_key": True,
        "notes": "以太坊主网"
    },

    # L2网络
    "arbitrum": {
        "api_service": "Arbiscan",
        "api_url": "https://api.arbiscan.io/v2/api",
        "api_key_url": "https://arbiscan.io/myapikey",
        "chainid": 42161,
        "uses_etherscan_key": False,
        "notes": "需要独立的Arbiscan API Key"
    },

    "optimism": {
        "api_service": "Optimism Etherscan",
        "api_url": "https://api-optimistic.etherscan.io/v2/api",
        "api_key_url": "https://optimistic.etherscan.io/myapikey",
        "chainid": 10,
        "uses_etherscan_key": True,
        "notes": "可使用Etherscan Key"
    },

    "base": {
        "api_service": "BaseScan",
        "api_url": "https://api.basescan.org/v2/api",
        "api_key_url": "https://basescan.org/myapikey",
        "chainid": 8453,
        "uses_etherscan_key": True,
        "notes": "可使用Etherscan Key (Coinbase运营)"
    },

    "blast": {
        "api_service": "BlastScan",
        "api_url": "https://api.blastscan.io/v2/api",
        "api_key_url": "https://blastscan.io/myapikey",
        "chainid": 81457,
        "uses_etherscan_key": True,
        "notes": "可使用Etherscan Key"
    },

    "linea": {
        "api_service": "Lineascan",
        "api_url": "https://api.lineascan.build/v2/api",
        "api_key_url": "https://lineascan.build/myapikey",
        "chainid": 59144,
        "uses_etherscan_key": True,
        "notes": "可使用Etherscan Key"
    },

    # 侧链
    "polygon": {
        "api_service": "PolygonScan",
        "api_url": "https://api.polygonscan.com/v2/api",
        "api_key_url": "https://polygonscan.com/myapikey",
        "chainid": 137,
        "uses_etherscan_key": False,
        "notes": "需要独立的PolygonScan API Key"
    },

    "bsc": {
        "api_service": "BscScan",
        "api_url": "https://api.bscscan.com/v2/api",
        "api_key_url": "https://bscscan.com/myapikey",
        "chainid": 56,
        "uses_etherscan_key": False,
        "notes": "需要独立的BscScan API Key"
    },

    "gnosis": {
        "api_service": "Gnosisscan",
        "api_url": "https://api.gnosisscan.io/v2/api",
        "api_key_url": "https://gnosisscan.io/myapikey",
        "chainid": 100,
        "uses_etherscan_key": False,
        "notes": "需要独立的Gnosisscan API Key"
    },

    # 其他L1
    "avalanche": {
        "api_service": "SnowTrace",
        "api_url": "https://api.snowtrace.io/v2/api",
        "api_key_url": "https://snowtrace.io/myapikey",
        "chainid": 43114,
        "uses_etherscan_key": False,
        "notes": "需要独立的SnowTrace API Key"
    },

    "fantom": {
        "api_service": "FTMScan",
        "api_url": "https://api.ftmscan.com/v2/api",
        "api_key_url": "https://ftmscan.com/myapikey",
        "chainid": 250,
        "uses_etherscan_key": False,
        "notes": "需要独立的FTMScan API Key"
    },

    "moonriver": {
        "api_service": "Moonscan",
        "api_url": "https://api-moonriver.moonscan.io/v2/api",
        "api_key_url": "https://moonriver.moonscan.io/myapikey",
        "chainid": 1285,
        "uses_etherscan_key": False,
        "notes": "需要独立的Moonscan API Key"
    },

    "mantle": {
        "api_service": "Mantle Explorer",
        "api_url": "https://explorer.mantle.xyz/api",
        "api_key_url": "https://explorer.mantle.xyz",
        "chainid": 5000,
        "uses_etherscan_key": False,
        "notes": "可能需要独立API Key或无需Key"
    },

    "sei": {
        "api_service": "Seitrace",
        "api_url": "https://seitrace.com/api",
        "api_key_url": "https://seitrace.com",
        "chainid": 1329,
        "uses_etherscan_key": False,
        "notes": "需要独立的Seitrace API Key"
    },
}


def analyze_networks(test_dir: Path):
    """分析所有脚本涉及的网络"""

    print("=" * 80)
    print("DeFi攻击脚本网络分析")
    print("=" * 80)

    # 统计数据
    network_stats = defaultdict(list)
    total_scripts = 0

    # 遍历所有.sol文件
    for sol_file in test_dir.glob("**/*.sol"):
        # 跳过非攻击脚本
        if "interface.sol" in sol_file.name or "basetest.sol" in sol_file.name:
            continue

        total_scripts += 1

        try:
            with open(sol_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 提取createSelectFork调用
            matches = re.findall(r'createSelectFork\s*\(\s*"([^"]+)"', content)

            for network in matches:
                # 过滤掉URL和特殊情况
                if network.startswith('http'):
                    continue
                if network in ['_chain', 'urlOrAlias']:
                    continue

                network_stats[network].append(sol_file.relative_to(test_dir))

        except Exception as e:
            pass

    # 排序并打印统计
    sorted_networks = sorted(network_stats.items(), key=lambda x: -len(x[1]))

    print(f"\n总攻击脚本数: {total_scripts}")
    print(f"涉及的网络数: {len(network_stats)}\n")

    print("## 网络使用统计\n")
    print(f"{'网络':<15} {'脚本数':<10} {'占比':<10} {'API服务':<20}")
    print("-" * 80)

    for network, scripts in sorted_networks:
        count = len(scripts)
        percentage = count / total_scripts * 100
        api_service = NETWORK_TO_API.get(network, {}).get('api_service', '未知')
        print(f"{network:<15} {count:<10} {percentage:>5.1f}%     {api_service:<20}")

    # API Key需求分析
    print("\n" + "=" * 80)
    print("API Key需求分析")
    print("=" * 80)

    # 按API Key分组
    etherscan_networks = []
    independent_networks = []
    unknown_networks = []

    for network in sorted_networks:
        net_name = network[0]
        count = len(network[1])

        if net_name not in NETWORK_TO_API:
            unknown_networks.append((net_name, count))
        elif NETWORK_TO_API[net_name]['uses_etherscan_key']:
            etherscan_networks.append((net_name, count))
        else:
            independent_networks.append((net_name, count))

    # 打印可使用Etherscan Key的网络
    print("\n### ✅ 可使用Etherscan API Key的网络")
    print(f"(您当前的Key: 2DTB79CHTEJ6PEDCTEINC8GV3IHUXHGP9A)\n")

    total_etherscan = sum(count for _, count in etherscan_networks)
    print(f"共 {len(etherscan_networks)} 个网络, {total_etherscan} 个脚本\n")

    for network, count in etherscan_networks:
        info = NETWORK_TO_API[network]
        print(f"  • {network:<15} ({count:>3} 脚本) - {info['notes']}")

    # 打印需要独立Key的网络
    print("\n### ⚠️  需要独立API Key的网络\n")

    total_independent = sum(count for _, count in independent_networks)
    print(f"共 {len(independent_networks)} 个网络, {total_independent} 个脚本\n")

    for network, count in independent_networks:
        info = NETWORK_TO_API[network]
        print(f"  • {network:<15} ({count:>3} 脚本)")
        print(f"    API服务: {info['api_service']}")
        print(f"    申请地址: {info['api_key_url']}")
        print(f"    备注: {info['notes']}\n")

    # 未知网络
    if unknown_networks:
        print("\n### ❓ 未识别的网络\n")
        for network, count in unknown_networks:
            print(f"  • {network:<15} ({count:>3} 脚本)")

    # 生成API Key申请指南
    print("\n" + "=" * 80)
    print("API Key申请指南")
    print("=" * 80)

    print("\n### 优先级1: 已有的Key")
    print(f"\n✅ Etherscan API Key: 2DTB79CHTEJ6PEDCTEINC8GV3IHUXHGP9A")
    print(f"   覆盖网络: {', '.join([n for n, _ in etherscan_networks])}")
    print(f"   覆盖脚本: {total_etherscan} 个 ({total_etherscan/total_scripts*100:.1f}%)")

    print("\n### 优先级2: 高频网络的Key (推荐申请)")

    # 找出脚本数>10的独立网络
    high_priority = [(n, c) for n, c in independent_networks if c >= 10]

    if high_priority:
        print("\n这些网络脚本数量多,建议优先申请:")
        for network, count in high_priority:
            info = NETWORK_TO_API[network]
            print(f"\n  {network.upper()}:")
            print(f"    脚本数: {count} ({count/total_scripts*100:.1f}%)")
            print(f"    申请: {info['api_key_url']}")

    print("\n### 优先级3: 低频网络的Key (可选)")

    low_priority = [(n, c) for n, c in independent_networks if c < 10]
    if low_priority:
        print(f"\n这些网络脚本较少,可按需申请:")
        for network, count in low_priority:
            info = NETWORK_TO_API[network]
            print(f"  • {network:<12} ({count:>2}个) - {info['api_key_url']}")

    # 保存详细报告
    report = {
        "summary": {
            "total_scripts": total_scripts,
            "total_networks": len(network_stats),
            "etherscan_compatible": {
                "networks": len(etherscan_networks),
                "scripts": total_etherscan,
                "percentage": round(total_etherscan/total_scripts*100, 1)
            },
            "independent_key_required": {
                "networks": len(independent_networks),
                "scripts": total_independent,
                "percentage": round(total_independent/total_scripts*100, 1)
            }
        },
        "networks": {}
    }

    for network, scripts in sorted_networks:
        report["networks"][network] = {
            "script_count": len(scripts),
            "percentage": round(len(scripts)/total_scripts*100, 1),
            "api_info": NETWORK_TO_API.get(network, {"api_service": "未知"}),
            "example_scripts": [str(s) for s in scripts[:5]]  # 前5个示例
        }

    report_file = Path("network_analysis_report.json")
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"\n\n详细报告已保存到: {report_file}")
    print("=" * 80)


def main():
    test_dir = Path.cwd()
    analyze_networks(test_dir)


if __name__ == '__main__':
    main()
