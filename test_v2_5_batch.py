#!/usr/bin/env python3
"""
V2.5批量测试脚本

在多个协议上测试V2.5,收集性能数据和质量指标
"""

import subprocess
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

# 测试协议列表
TEST_PROTOCOLS = [
    'BarleyFinance_exp',
    'XSIJ_exp',
    'Gamma_exp',
    'WiseLending02_exp',
    'CitadelFinance_exp',
]

YEAR_MONTH = '2024-01'

class TestResult:
    def __init__(self, protocol: str):
        self.protocol = protocol
        self.success = False
        self.execution_time = 0.0
        self.constraints_count = 0
        self.v3_available = False
        self.v3_layout_init = False
        self.v3_eval_init = False
        self.v3_slot_inferences = 0
        self.v3_eval_successes = 0
        self.v3_eval_failures = 0
        self.error_msg = None
        self.output_log = []

def run_test(protocol: str) -> TestResult:
    """运行单个协议的测试"""
    result = TestResult(protocol)

    print(f"\n{'='*60}")
    print(f"测试协议: {protocol}")
    print(f"{'='*60}")

    start_time = time.time()

    try:
        cmd = [
            'python3',
            'extract_param_state_constraints_v2_5.py',
            '--protocol', protocol,
            '--year-month', YEAR_MONTH
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd='/home/dqy/Firewall/FirewallOnchain/DeFiHackLabs'
        )

        result.execution_time = time.time() - start_time
        result.output_log = proc.stdout.split('\n')

        # 解析输出
        for line in result.output_log:
            if 'V3增强组件已加载' in line:
                result.v3_available = True
            elif 'V3 StorageLayoutInferrer已初始化' in line:
                result.v3_layout_init = True
            elif 'V3 SymbolicParameterEvaluator已初始化' in line:
                result.v3_eval_init = True
            elif 'V3推断slot' in line and '→' in line:
                result.v3_slot_inferences += 1
            elif 'V3精确求值:' in line:
                result.v3_eval_successes += 1
            elif 'V3求值失败' in line or 'V3推断失败' in line:
                result.v3_eval_failures += 1
            elif '生成约束:' in line:
                try:
                    parts = line.split('生成约束:')[1].strip().split()
                    result.constraints_count = int(parts[0])
                except:
                    pass

        # 检查是否成功
        if proc.returncode == 0 and result.constraints_count > 0:
            result.success = True
            print(f"✅ 测试成功 - 生成 {result.constraints_count} 个约束")
        else:
            result.error_msg = proc.stderr or "未知错误"
            print(f"❌ 测试失败: {result.error_msg[:100]}")

        # 读取生成的约束文件
        constraint_file = Path(f'/home/dqy/Firewall/FirewallOnchain/DeFiHackLabs/extracted_contracts/{YEAR_MONTH}/{protocol}/constraint_rules_v2.json')
        if constraint_file.exists():
            with open(constraint_file, 'r') as f:
                data = json.load(f)
                result.constraints_count = len(data.get('constraints', []))

    except subprocess.TimeoutExpired:
        result.error_msg = "执行超时(>120s)"
        result.execution_time = 120.0
        print(f"⏱️  超时")
    except Exception as e:
        result.error_msg = str(e)
        result.execution_time = time.time() - start_time
        print(f"💥 异常: {e}")

    return result

def print_summary(results: List[TestResult]):
    """打印测试摘要"""
    print("\n" + "="*80)
    print("V2.5批量测试摘要报告")
    print("="*80)

    # 总体统计
    total = len(results)
    successful = sum(1 for r in results if r.success)
    failed = total - successful

    print(f"\n📊 总体统计:")
    print(f"  总测试数: {total}")
    print(f"  成功: {successful} ({successful/total*100:.1f}%)")
    print(f"  失败: {failed} ({failed/total*100:.1f}%)")

    # V3组件使用统计
    v3_available_count = sum(1 for r in results if r.v3_available)
    v3_layout_count = sum(1 for r in results if r.v3_layout_init)
    v3_eval_count = sum(1 for r in results if r.v3_eval_init)

    print(f"\n🔧 V3组件统计:")
    print(f"  V3可用: {v3_available_count}/{total}")
    print(f"  StorageLayoutInferrer初始化: {v3_layout_count}/{total}")
    print(f"  SymbolicParameterEvaluator初始化: {v3_eval_count}/{total}")

    # V3性能统计
    total_slot_inferences = sum(r.v3_slot_inferences for r in results)
    total_eval_successes = sum(r.v3_eval_successes for r in results)
    total_eval_failures = sum(r.v3_eval_failures for r in results)

    print(f"\n📈 V3性能统计:")
    print(f"  Slot语义推断: {total_slot_inferences} 次")
    print(f"  参数求值成功: {total_eval_successes} 次")
    print(f"  参数求值失败(回退V2): {total_eval_failures} 次")
    if total_eval_successes + total_eval_failures > 0:
        success_rate = total_eval_successes / (total_eval_successes + total_eval_failures) * 100
        print(f"  求值成功率: {success_rate:.1f}%")

    # 约束生成统计
    total_constraints = sum(r.constraints_count for r in results if r.success)
    avg_constraints = total_constraints / successful if successful > 0 else 0

    print(f"\n📝 约束生成统计:")
    print(f"  总约束数: {total_constraints}")
    print(f"  平均每协议: {avg_constraints:.1f}")

    # 性能统计
    successful_results = [r for r in results if r.success]
    if successful_results:
        avg_time = sum(r.execution_time for r in successful_results) / len(successful_results)
        min_time = min(r.execution_time for r in successful_results)
        max_time = max(r.execution_time for r in successful_results)

        print(f"\n⏱️  执行时间统计:")
        print(f"  平均: {avg_time:.2f}s")
        print(f"  最快: {min_time:.2f}s")
        print(f"  最慢: {max_time:.2f}s")

    # 详细结果表
    print(f"\n📋 详细结果:")
    print(f"{'协议':<25} {'状态':<8} {'约束数':<8} {'V3推断':<8} {'V3求值':<12} {'耗时':<10}")
    print("-" * 80)

    for r in results:
        status = "✅ 成功" if r.success else "❌ 失败"
        v3_inferences = f"{r.v3_slot_inferences}次" if r.v3_slot_inferences > 0 else "-"
        v3_evals = f"{r.v3_eval_successes}/{r.v3_eval_failures}" if (r.v3_eval_successes + r.v3_eval_failures) > 0 else "-"
        time_str = f"{r.execution_time:.2f}s"

        print(f"{r.protocol:<25} {status:<8} {r.constraints_count:<8} {v3_inferences:<8} {v3_evals:<12} {time_str:<10}")

        if not r.success and r.error_msg:
            print(f"  ⚠️  错误: {r.error_msg[:60]}...")

    # 失败原因分析
    if failed > 0:
        print(f"\n⚠️  失败原因:")
        for r in results:
            if not r.success:
                print(f"  - {r.protocol}: {r.error_msg[:80]}")

def save_detailed_report(results: List[TestResult]):
    """保存详细报告到JSON"""
    report = {
        'test_date': time.strftime('%Y-%m-%d %H:%M:%S'),
        'version': 'V2.5',
        'total_protocols': len(results),
        'successful': sum(1 for r in results if r.success),
        'failed': sum(1 for r in results if not r.success),
        'results': []
    }

    for r in results:
        report['results'].append({
            'protocol': r.protocol,
            'success': r.success,
            'execution_time': r.execution_time,
            'constraints_count': r.constraints_count,
            'v3_available': r.v3_available,
            'v3_layout_init': r.v3_layout_init,
            'v3_eval_init': r.v3_eval_init,
            'v3_slot_inferences': r.v3_slot_inferences,
            'v3_eval_successes': r.v3_eval_successes,
            'v3_eval_failures': r.v3_eval_failures,
            'error_msg': r.error_msg
        })

    output_path = Path('/home/dqy/Firewall/FirewallOnchain/v2_5_batch_test_results.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n💾 详细报告已保存: {output_path}")

def main():
    print("="*80)
    print("V2.5批量测试 - 开始")
    print(f"测试协议数: {len(TEST_PROTOCOLS)}")
    print("="*80)

    results = []

    for protocol in TEST_PROTOCOLS:
        result = run_test(protocol)
        results.append(result)

        # 短暂延迟避免资源竞争
        time.sleep(1)

    print_summary(results)
    save_detailed_report(results)

    print("\n✨ 批量测试完成!")

if __name__ == '__main__':
    main()
