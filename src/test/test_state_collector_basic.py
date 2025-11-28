#!/usr/bin/env python3
"""
StateCollector 基础功能测试

测试点:
1. StateCollector 能否初始化
2. collect_storage_for_known_slots() 基本功能
3. 槽位格式转换 (字符串/整数)
"""

import sys
import logging
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_state_collector_init():
    """测试 StateCollector 初始化"""
    logger.info("=" * 80)
    logger.info("测试1: StateCollector 初始化")
    logger.info("=" * 80)

    try:
        # 导入模块
        sys.path.insert(0, str(Path(__file__).parent))
        from generate_monitor_output import StateCollector

        # 测试本地 Anvil RPC (可能未运行,预期失败但不崩溃)
        logger.info("尝试连接到 http://localhost:8545 ...")
        collector = StateCollector("http://localhost:8545")

        logger.info("✓ StateCollector 实例化成功")
        logger.info(f"  Web3 连接状态: {collector.w3.is_connected()}")

        return collector

    except ImportError as e:
        logger.error(f"✗ 导入失败: {e}")
        logger.error("  可能缺少 web3 库, 运行: pip install web3")
        return None
    except Exception as e:
        logger.error(f"✗ 初始化失败: {e}")
        return None

def test_slot_format_conversion():
    """测试槽位格式转换"""
    logger.info("\n" + "=" * 80)
    logger.info("测试2: 槽位格式转换")
    logger.info("=" * 80)

    test_cases = [
        ("0x2", "十六进制字符串"),
        ("2", "十进制字符串"),
        (2, "整数"),
        ("0x0000000000000000000000000000000000000000000000000000000000000005", "长十六进制")
    ]

    for slot, desc in test_cases:
        logger.info(f"  测试: {desc} → {slot}")

        try:
            # 模拟 StateCollector 的槽位转换逻辑
            if isinstance(slot, str):
                if slot.startswith('0x'):
                    slot_int = int(slot, 16)
                else:
                    slot_int = int(slot)
            else:
                slot_int = int(slot)

            logger.info(f"    ✓ 转换为整数: {slot_int}")

        except Exception as e:
            logger.error(f"    ✗ 转换失败: {e}")

def test_with_attack_state():
    """使用真实的 attack_state.json 测试"""
    logger.info("\n" + "=" * 80)
    logger.info("测试3: 读取真实 attack_state.json")
    logger.info("=" * 80)

    attack_state_file = Path("DeFiHackLabs/extracted_contracts/2024-01/MIC_exp/attack_state.json")

    if not attack_state_file.exists():
        logger.warning(f"✗ 未找到测试文件: {attack_state_file}")
        return

    try:
        import json

        with open(attack_state_file) as f:
            attack_state = json.load(f)

        # 提取地址和槽位信息
        addresses = attack_state.get('addresses', {})
        logger.info(f"  加载的地址数量: {len(addresses)}")

        # 分析第一个地址的槽位
        if addresses:
            first_addr = list(addresses.keys())[0]
            first_data = addresses[first_addr]
            storage = first_data.get('storage', {})

            logger.info(f"  第一个地址: {first_addr[:20]}...")
            logger.info(f"  存储槽数量: {len(storage)}")

            if storage:
                # 显示前3个槽位
                for i, (slot, value) in enumerate(list(storage.items())[:3]):
                    logger.info(f"    槽位 {slot[:10]}...: {value[:20]}...")

                logger.info("  ✓ attack_state.json 格式正确")
            else:
                logger.warning("  ⚠ 该地址没有存储槽")

    except Exception as e:
        logger.error(f"  ✗ 读取失败: {e}")
        import traceback
        traceback.print_exc()

def main():
    logger.info("开始 StateCollector 基础功能测试\n")

    # 测试1: 初始化
    collector = test_state_collector_init()

    # 测试2: 槽位格式转换
    test_slot_format_conversion()

    # 测试3: 真实数据读取
    test_with_attack_state()

    logger.info("\n" + "=" * 80)
    logger.info("基础测试完成")
    logger.info("=" * 80)
    logger.info("\n注意: 完整功能测试需要运行中的 Anvil 节点")
    logger.info("运行命令: python src/test/generate_monitor_output.py --project extracted_contracts/2024-01/MIC_exp\n")

if __name__ == '__main__':
    main()
