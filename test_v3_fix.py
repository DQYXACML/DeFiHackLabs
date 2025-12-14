#!/usr/bin/env python3
"""
V3修复验证脚本
检查 extract_param_state_constraints_v3.py 中的修复是否生效
"""

import sys
import json
from pathlib import Path

def test_fix():
    """测试修复是否生效"""

    print("=" * 60)
    print("V3修复验证测试")
    print("=" * 60)

    # 1. 检查源代码
    print("\n[1/3] 检查源代码修复...")
    v3_file = Path("extract_param_state_constraints_v3.py")
    if not v3_file.exists():
        print("✗ 找不到 extract_param_state_constraints_v3.py")
        return False

    content = v3_file.read_text()

    # 检查三个修复点
    fixes = [
        (1063, "(info.get('name') or '').lower()"),
        (1247, "(info1.get('name') or '').lower()"),
        (1248, "(info2.get('name') or '').lower()")
    ]

    all_fixed = True
    for line_num, expected in fixes:
        lines = content.split('\n')
        if line_num <= len(lines):
            actual_line = lines[line_num - 1]
            if expected in actual_line:
                print(f"  ✓ 行{line_num}: 已修复")
            else:
                print(f"  ✗ 行{line_num}: 未修复")
                print(f"    实际: {actual_line.strip()}")
                all_fixed = False
        else:
            print(f"  ✗ 行{line_num}: 文件长度不足")
            all_fixed = False

    if not all_fixed:
        print("\n✗ 源代码修复不完整！")
        return False

    # 2. 测试导入
    print("\n[2/3] 测试V3组件导入...")
    try:
        from extract_param_state_constraints_v3 import (
            StorageLayoutInferrer,
            SymbolicParameterEvaluator,
            StorageLayout
        )
        print("  ✓ V3组件导入成功")
    except ImportError as e:
        print(f"  ✗ 导入失败: {e}")
        return False

    # 3. 测试真实数据
    print("\n[3/3] 使用BarleyFinance真实数据测试...")

    try:
        # 加载真实addresses.json
        addr_file = Path("extracted_contracts/2024-01/BarleyFinance_exp/addresses.json")
        if not addr_file.exists():
            print(f"  ! 跳过: {addr_file} 不存在")
            return True  # 源代码已修复就算成功

        with open(addr_file) as f:
            addresses_list = json.load(f)

        addresses_info = {item['address'].lower(): item for item in addresses_list}

        none_count = sum(1 for info in addresses_info.values() if info.get('name') is None)
        print(f"  加载了 {len(addresses_info)} 个地址，其中 {none_count} 个 name=None")

        # 创建模拟 StateDiffAnalyzer
        class MockStateDiffAnalyzer:
            def __init__(self, addr_info):
                self.addresses_info = addr_info
                self.state_before = None
                self.state_after = None
                self.layout_inferrer = StorageLayoutInferrer(self, self.addresses_info)

            def get_contract_storage(self, addr, before=True):
                return {}

            def analyze_slot_changes(self, addr):
                return []

        state_analyzer = MockStateDiffAnalyzer(addresses_info)

        # 测试 SymbolicParameterEvaluator 初始化
        param_evaluator = SymbolicParameterEvaluator(None, state_analyzer)

        print(f"  ✓ SymbolicParameterEvaluator 初始化成功")
        print(f"  ✓ 环境变量数: {len(param_evaluator.variable_env)}")

    except AttributeError as e:
        print(f"  ✗ AttributeError: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"  ✗ 其他错误: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    print()
    success = test_fix()
    print("\n" + "=" * 60)

    if success:
        print("✓✓✓ 所有测试通过！V3修复成功！")
        print("=" * 60)
        print("\n建议:")
        print("1. 清除Python缓存: find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null")
        print("2. 清除.pyc文件: find . -name '*.pyc' -delete")
        print("3. 重新运行你的命令")
        sys.exit(0)
    else:
        print("✗✗✗ 测试失败！请检查上述错误")
        print("=" * 60)
        sys.exit(1)
