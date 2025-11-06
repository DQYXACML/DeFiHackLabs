#!/usr/bin/env python3
"""
端到端攻击验证 + 不变量检测脚本

完整工作流:
1. 启动空白 Anvil
2. 部署合约并恢复状态
3. 验证部署
4. 运行简化版攻击
5. 使用 Monitor 分析交易
6. 检查不变量违规
7. 生成验证报告
"""

import os
import sys
import json
import subprocess
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# 导入自定义工具
sys.path.append(str(Path(__file__).parent))
from anvil_utils import AnvilManager
from deployment_verifier import DeploymentVerifier

logger = logging.getLogger(__name__)


class AttackVerifier:
    """攻击和不变量验证器"""

    def __init__(self, event_name: str, year_month: str, rpc_url: str = "http://localhost:8545", use_fork: bool = False):
        self.event_name = event_name
        self.year_month = year_month
        self.rpc_url = rpc_url
        self.use_fork = use_fork  # 是否使用 fork 模式

        # 文件路径
        self.attack_state_file = Path(f"extracted_contracts/{year_month}/{event_name}/attack_state.json")
        self.invariants_file = Path(f"extracted_contracts/{year_month}/{event_name}/invariants.json")
        self.deploy_script = Path(f"generated_deploy/script/{year_month}/deploy_{event_name}.py")
        self.attack_script_local = Path(f"src/test/{year_month}/{event_name}_local.sol")
        self.attack_script_original = Path(f"src/test/{year_month}/{event_name}.sol")
        # 根据模式选择攻击脚本
        self.attack_script = self.attack_script_original if use_fork else self.attack_script_local
        self.monitor_binary = Path("autopath/monitor")
        # 注意：文件名需要与 generate_monitor_output.py 生成的文件名一致
        self.monitor_output = Path(f"autopath/{event_name}_analysis.json")
        self.report_file = Path(f"reports/{event_name}_verification.md")

    def verify(self) -> bool:
        """执行完整验证流程"""
        print("=" * 80)
        print(f"开始验证 {self.event_name} 攻击")
        if self.use_fork:
            print("模式: Fork 主网")
        else:
            print("模式: 空白 Anvil + 部署状态")
        print("=" * 80)

        try:
            # 步骤 1: 检查必需文件
            if not self._check_prerequisites():
                return False

            # 步骤 2: 启动 Anvil
            print("\n🚀 [1/7] 启动 Anvil...")
            if self.use_fork:
                # Fork 模式：读取区块号
                with open(self.attack_state_file) as f:
                    attack_state = json.load(f)
                fork_block = attack_state['metadata']['block_number']
                fork_url = "https://eth-mainnet.g.alchemy.com/v2/oKxs-03sij-U_N0iOlrSsZFr29-IqbuF"
                anvil = AnvilManager(port=8545, fork_url=fork_url, fork_block=fork_block)
            else:
                # 空白模式
                anvil = AnvilManager(port=8545)

            if not anvil.start():
                logger.error("无法启动 Anvil")
                return False

            try:
                if not self.use_fork:
                    # 只在非 fork 模式下部署和验证
                    # 步骤 3: 部署合约
                    print("\n📦 [2/7] 部署合约并恢复状态...")
                    if not self._deploy_contracts():
                        return False

                    # 步骤 4: 验证部署
                    print("\n✅ [3/7] 验证部署...")
                    if not self._verify_deployment():
                        return False
                else:
                    print("\n📦 [2/7] 跳过部署（fork 模式）...")
                    print("\n✅ [3/7] 跳过验证（fork 模式）...")

                # 步骤 5: 运行攻击
                print("\n⚔️  [4/7] 运行攻击...")

                # 攻击前：拍摄存储快照
                print("  📸 拍摄攻击前的存储快照...")
                with open(self.invariants_file) as f:
                    invariants_data = json.load(f)
                invariants = invariants_data.get('storage_invariants', [])

                storage_before = self._capture_storage_snapshot(invariants)
                if storage_before:
                    print(f"  ✓ 已捕获 {len(storage_before)} 个合约的存储状态")

                # 执行攻击
                tx_hash = self._run_attack()
                if not tx_hash:
                    return False

                # 攻击后：再次拍摄快照
                print("  📸 拍摄攻击后的存储快照...")
                storage_after = self._capture_storage_snapshot(invariants)
                if storage_after:
                    print(f"  ✓ 已捕获攻击后的存储状态")

                # 计算存储变化
                storage_changes = self._compute_storage_changes(storage_before, storage_after)

                # 步骤 6: Monitor 分析
                print("\n🛡️  [5/7] 运行 Monitor 分析...")
                if not self._run_monitor(tx_hash):
                    return False

                # 步骤 7: 检查不变量
                print("\n🔬 [6/7] 检查不变量违规...")
                violations = self._check_invariants(storage_changes)

                # 步骤 8: 生成报告
                print("\n📊 [7/7] 生成验证报告...")
                self._generate_report(violations, tx_hash)

                # 打印结果摘要
                self._print_summary(violations)

                return True

            finally:
                # 清理：停止 Anvil
                print("\n🧹 停止 Anvil...")
                anvil.stop()

        except Exception as e:
            logger.error(f"验证过程中出错: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _check_prerequisites(self) -> bool:
        """检查必需文件"""
        missing_files = []

        if not self.attack_state_file.exists():
            missing_files.append(str(self.attack_state_file))
        if not self.invariants_file.exists():
            missing_files.append(str(self.invariants_file))
        if not self.deploy_script.exists():
            missing_files.append(str(self.deploy_script))
        if not self.attack_script.exists():
            missing_files.append(str(self.attack_script))
        if not self.monitor_binary.exists():
            missing_files.append(str(self.monitor_binary))

        if missing_files:
            logger.error("缺少必需文件:")
            for f in missing_files:
                logger.error(f"  - {f}")
            return False

        return True

    def _deploy_contracts(self) -> bool:
        """部署合约"""
        try:
            result = subprocess.run(
                ["python", str(self.deploy_script), self.rpc_url],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.error(f"部署失败: {result.stderr}")
                return False

            print("  ✓ 部署成功")
            return True

        except subprocess.TimeoutExpired:
            logger.error("部署超时")
            return False
        except Exception as e:
            logger.error(f"部署出错: {e}")
            return False

    def _verify_deployment(self) -> bool:
        """验证部署"""
        try:
            verifier = DeploymentVerifier(self.rpc_url)
            passed, errors = verifier.verify(self.attack_state_file)

            if not passed:
                logger.error("部署验证失败:")
                for err in errors[:5]:  # 只显示前 5 个错误
                    logger.error(f"  {err}")
                return False

            print("  ✓ 验证通过")
            return True

        except Exception as e:
            logger.error(f"验证出错: {e}")
            return False

    def _run_attack(self) -> Optional[str]:
        """运行攻击并返回交易 hash"""
        try:
            # 运行 forge test
            result = subprocess.run(
                [
                    "forge", "test",
                    "--contracts", str(self.attack_script),
                    "--rpc-url", self.rpc_url,
                    "-vvv"
                ],
                capture_output=True,
                text=True,
                timeout=120
            )

            # 检查是否成功
            if "testExploit" not in result.stdout or result.returncode != 0:
                logger.error("攻击执行失败")
                logger.debug(result.stdout)
                logger.debug(result.stderr)
                return None

            print("  ✓ 攻击执行成功")

            # 提取交易 hash
            tx_hash = self._extract_tx_hash()
            if tx_hash:
                print(f"  交易 hash: {tx_hash}")
                return tx_hash
            else:
                logger.warning("无法提取交易 hash")
                return None

        except subprocess.TimeoutExpired:
            logger.error("攻击执行超时")
            return None
        except Exception as e:
            logger.error(f"攻击执行出错: {e}")
            return None

    def _extract_tx_hash(self) -> Optional[str]:
        """从 Anvil 提取攻击交易 hash（找 gas 使用最高的交易）"""
        try:
            # 获取当前区块号
            result = subprocess.run(
                ["cast", "block-number", "--rpc-url", self.rpc_url],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                return None

            latest_block = int(result.stdout.strip())

            # 检查最近几个区块的所有交易，找gas最高的
            max_gas = 0
            target_tx = None

            for block_num in range(max(0, latest_block - 5), latest_block + 1):
                result = subprocess.run(
                    ["cast", "block", str(block_num), "--rpc-url", self.rpc_url, "--json"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    try:
                        block = json.loads(result.stdout)
                        transactions = block.get('transactions', [])

                        # 获取每个交易的 gas 使用量
                        for tx_hash in transactions:
                            tx_result = subprocess.run(
                                ["cast", "receipt", tx_hash, "--rpc-url", self.rpc_url, "--json"],
                                capture_output=True,
                                text=True,
                                timeout=10
                            )

                            if tx_result.returncode == 0:
                                receipt = json.loads(tx_result.stdout)
                                gas_used = int(receipt.get('gasUsed', '0'), 16)

                                # 选择 gas 使用最高的交易（通常是攻击交易）
                                if gas_used > max_gas and gas_used > 100000:  # 过滤简单转账
                                    max_gas = gas_used
                                    target_tx = tx_hash

                    except json.JSONDecodeError:
                        continue

            if target_tx:
                logger.info(f"找到攻击交易 (gas: {max_gas}): {target_tx}")
                return target_tx

            return None

        except Exception as e:
            logger.warning(f"提取交易 hash 失败: {e}")
            return None

    def _capture_storage_snapshot(self, invariants: List[Dict]) -> Dict:
        """
        拍摄存储快照：捕获所有不变量相关的存储槽当前值

        Args:
            invariants: 不变量定义列表

        Returns:
            存储快照 {contract_addr: {slot: value}}
        """
        snapshot = {}

        try:
            # 收集需要查询的合约和槽位
            queries = set()
            for inv in invariants:
                if 'slots' in inv:
                    slots_info = inv['slots']
                    if 'contract' in slots_info and 'monitored_slot' in slots_info:
                        contract = slots_info['contract']
                        slot = int(slots_info['monitored_slot'])
                        queries.add((contract, slot))

            # 查询每个存储槽的当前值
            for contract, slot in queries:
                result = subprocess.run(
                    ["cast", "storage", contract, str(slot), "--rpc-url", self.rpc_url],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    value = int(result.stdout.strip(), 16)

                    if contract not in snapshot:
                        snapshot[contract] = {}

                    snapshot[contract][slot] = value
                    logger.debug(f"    {contract}[{slot}] = {value}")
                else:
                    logger.warning(f"    无法读取 {contract}[{slot}]: {result.stderr}")

        except Exception as e:
            logger.error(f"拍摄存储快照失败: {e}")

        return snapshot

    def _compute_storage_changes(self, before: Dict, after: Dict) -> Dict:
        """
        计算存储变化

        Args:
            before: 攻击前的存储快照
            after: 攻击后的存储快照

        Returns:
            存储变化字典 {contract_addr: {slot: {before, after, change_rate}}}
        """
        changes = {}

        try:
            # 遍历所有合约
            all_contracts = set(before.keys()) | set(after.keys())

            for contract in all_contracts:
                before_slots = before.get(contract, {})
                after_slots = after.get(contract, {})

                # 遍历所有槽位
                all_slots = set(before_slots.keys()) | set(after_slots.keys())

                for slot in all_slots:
                    value_before = before_slots.get(slot, 0)
                    value_after = after_slots.get(slot, 0)

                    # 计算变化率
                    change_rate = 0.0
                    if value_before > 0:
                        change_rate = abs(value_after - value_before) / value_before

                    if contract not in changes:
                        changes[contract] = {}

                    changes[contract][slot] = {
                        'before': value_before,
                        'after': value_after,
                        'change_rate': change_rate,
                        'change_pct': change_rate * 100,
                        'change_abs': value_after - value_before
                    }

                    logger.debug(f"  {contract}[{slot}]: {value_before} → {value_after} ({change_rate:.2%})")

        except Exception as e:
            logger.error(f"计算存储变化失败: {e}")

        return changes

    def _run_monitor(self, tx_hash: str) -> bool:
        """运行 Monitor 分析"""
        try:
            result = subprocess.run(
                [
                    str(self.monitor_binary),
                    "-rpc", self.rpc_url,
                    "-tx", tx_hash,
                    "-output", str(self.monitor_output),
                    "-v"
                ],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.error(f"Monitor 分析失败: {result.stderr}")
                return False

            if not self.monitor_output.exists():
                logger.error("Monitor 未生成输出文件")
                return False

            print("  ✓ 分析完成")
            print(f"  输出: {self.monitor_output}")
            return True

        except subprocess.TimeoutExpired:
            logger.error("Monitor 分析超时")
            return False
        except Exception as e:
            logger.error(f"Monitor 分析出错: {e}")
            return False

    def _check_invariants(self, storage_changes: Dict) -> List[Dict]:
        """检查不变量违规（存储级 + 运行时）"""
        violations = []

        try:
            # 读取不变量定义
            with open(self.invariants_file) as f:
                invariants_data = json.load(f)

            storage_invariants = invariants_data.get('storage_invariants', [])
            runtime_invariants = invariants_data.get('runtime_invariants', [])

            total_invariants = len(storage_invariants) + len(runtime_invariants)
            print(f"  检查 {total_invariants} 个不变量:")
            print(f"    - 存储级: {len(storage_invariants)}")
            print(f"    - 运行时: {len(runtime_invariants)}")

            # 检查存储级不变量
            for inv in storage_invariants:
                violation = self._check_single_invariant(inv, storage_changes)
                if violation:
                    violations.append(violation)
                    print(f"  ⚠️  {inv['id']}: {inv['description'][:50]}...")

            # 检查运行时不变量
            for inv in runtime_invariants:
                violation = self._check_runtime_invariant(inv)
                if violation:
                    violations.append(violation)
                    print(f"  ⚠️  {inv['id']}: {inv['description'][:50]}...")

            if not violations:
                print("  ✓ 未检测到不变量违规")

            return violations

        except Exception as e:
            logger.error(f"检查不变量时出错: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _check_single_invariant(self, inv: Dict, storage_changes: Dict) -> Optional[Dict]:
        """检查单个不变量"""
        inv_type = inv.get('type')

        # 根据不变量类型检查
        if inv_type == 'bounded_change_rate':
            return self._check_change_rate(inv, storage_changes)
        elif inv_type == 'share_price_stability':
            return self._check_share_price(inv, storage_changes)
        elif inv_type == 'supply_backing_consistency':
            return self._check_supply_backing(inv, storage_changes)

        return None

    def _check_change_rate(self, inv: Dict, storage_changes: Dict) -> Optional[Dict]:
        """检查变化率不变量"""
        try:
            slots_info = inv.get('slots', {})
            contract = slots_info.get('contract')
            slot = int(slots_info.get('monitored_slot', -1))
            threshold = inv.get('threshold', 0.5)

            if contract not in storage_changes or slot not in storage_changes[contract]:
                return None

            slot_data = storage_changes[contract][slot]
            change_rate = slot_data['change_rate']

            # 检查是否超过阈值
            if change_rate > threshold:
                return {
                    'invariant_id': inv['id'],
                    'invariant_type': inv['type'],
                    'severity': inv['severity'],
                    'description': inv['description'],
                    'threshold': threshold,
                    'actual_value': change_rate,
                    'change_rate': change_rate,
                    'before': slot_data['before'],
                    'after': slot_data['after'],
                    'contract': contract,
                    'slot': slot
                }

            return None

        except Exception as e:
            logger.debug(f"检查 {inv['id']} 时出错: {e}")
            return None

    def _check_share_price(self, inv: Dict, storage_changes: Dict) -> Optional[Dict]:
        """检查份额价格稳定性（简化实现）"""
        # 实际实现需要更复杂的逻辑来计算份额价格变化
        # 这里提供一个框架
        return None

    def _check_supply_backing(self, inv: Dict, storage_changes: Dict) -> Optional[Dict]:
        """检查供应量支撑一致性（简化实现）"""
        # 实际实现需要更复杂的逻辑
        return None

    def _check_runtime_invariant(self, inv: Dict) -> Optional[Dict]:
        """
        检查运行时不变量

        从 Monitor 输出中提取实际运行时指标，与不变量定义的阈值比较

        Args:
            inv: 运行时不变量定义

        Returns:
            如果违规，返回违规详情；否则返回 None
        """
        try:
            # 读取 Monitor 输出
            if not self.monitor_output.exists():
                logger.debug(f"Monitor 输出文件不存在，跳过运行时不变量检查")
                return None

            with open(self.monitor_output) as f:
                monitor_data = json.load(f)

            tx_data = monitor_data.get('transaction_data', {})
            inv_type = inv.get('type')

            # 根据不变量类型检查
            if inv_type == 'runtime_loop_limit':
                return self._check_loop_limit(inv, tx_data)
            elif inv_type == 'runtime_call_depth_limit':
                return self._check_call_depth_limit(inv, tx_data)
            elif inv_type == 'runtime_reentrancy_limit':
                return self._check_reentrancy_limit(inv, tx_data)
            elif inv_type == 'runtime_balance_change_limit':
                return self._check_balance_change_limit(inv, tx_data)

            return None

        except Exception as e:
            logger.debug(f"检查运行时不变量 {inv.get('id')} 时出错: {e}")
            return None

    def _check_loop_limit(self, inv: Dict, tx_data: Dict) -> Optional[Dict]:
        """检查循环次数限制"""
        threshold = inv.get('threshold', 0)
        actual_value = tx_data.get('loop_iterations', 0)

        if actual_value > threshold:
            return {
                'invariant_id': inv['id'],
                'invariant_type': inv['type'],
                'severity': inv['severity'],
                'description': inv['description'],
                'threshold': threshold,
                'actual_value': actual_value,
                'rationale': inv.get('rationale', '')
            }

        return None

    def _check_call_depth_limit(self, inv: Dict, tx_data: Dict) -> Optional[Dict]:
        """检查调用深度限制"""
        threshold = inv.get('threshold', 0)
        actual_value = tx_data.get('call_depth', 0)

        if actual_value > threshold:
            return {
                'invariant_id': inv['id'],
                'invariant_type': inv['type'],
                'severity': inv['severity'],
                'description': inv['description'],
                'threshold': threshold,
                'actual_value': actual_value,
                'rationale': inv.get('rationale', '')
            }

        return None

    def _check_reentrancy_limit(self, inv: Dict, tx_data: Dict) -> Optional[Dict]:
        """检查重入深度限制"""
        threshold = inv.get('threshold', 0)
        actual_value = tx_data.get('reentrancy_depth', 0)

        if actual_value > threshold:
            return {
                'invariant_id': inv['id'],
                'invariant_type': inv['type'],
                'severity': inv['severity'],
                'description': inv['description'],
                'threshold': threshold,
                'actual_value': actual_value,
                'rationale': inv.get('rationale', '')
            }

        return None

    def _check_balance_change_limit(self, inv: Dict, tx_data: Dict) -> Optional[Dict]:
        """检查余额变化率限制"""
        threshold = inv.get('threshold', 0)
        balance_changes = tx_data.get('balance_changes', {})

        # 找到最大变化率
        max_change_rate = 0
        max_change_addr = None

        for addr, change_data in balance_changes.items():
            change_rate = abs(change_data.get('change_rate', 0))
            if change_rate > max_change_rate:
                max_change_rate = change_rate
                max_change_addr = addr

        if max_change_rate > threshold:
            return {
                'invariant_id': inv['id'],
                'invariant_type': inv['type'],
                'severity': inv['severity'],
                'description': inv['description'],
                'threshold': threshold,
                'actual_value': max_change_rate,
                'max_change_address': max_change_addr,
                'rationale': inv.get('rationale', '')
            }

        return None

    def _generate_report(self, violations: List[Dict], tx_hash: str):
        """生成 Markdown 验证报告"""
        try:
            # 确保报告目录存在
            self.report_file.parent.mkdir(parents=True, exist_ok=True)

            # 读取 Monitor 数据
            with open(self.monitor_output) as f:
                monitor_data = json.load(f)

            tx_data = monitor_data.get('transaction_data', {})

            # 生成报告
            report = self._format_report(violations, tx_hash, tx_data)

            # 保存报告
            with open(self.report_file, 'w') as f:
                f.write(report)

            print(f"  ✓ 报告已保存: {self.report_file}")

        except Exception as e:
            logger.error(f"生成报告时出错: {e}")

    def _format_report(self, violations: List[Dict], tx_hash: str, tx_data: Dict) -> str:
        """格式化报告"""
        report = f"""# {self.event_name} 攻击验证报告

生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 🎯 攻击结果

- **攻击是否成功**: {'✅ 是' if violations else '❌ 否'}
- **检测到的违规**: {len(violations)}
- **交易 Hash**: `{tx_hash}`

---

## ⚠️  不变量违规详情

"""

        if violations:
            for v in violations:
                report += f"""### {v['invariant_id']}: {v['description']}

- **严重性**: `{v['severity']}`
- **阈值**: {v.get('threshold', 'N/A')}
- **实际值**: {v.get('actual_value', 'N/A')}
- **变化率**: {v.get('change_rate', 0):.2%}

"""
        else:
            report += "✅ 未检测到不变量违规\n\n"

        report += """---

## 📊 Monitor 分析数据

### 交易基本信息

"""

        report += f"""- **交易 Hash**: `{tx_data.get('tx_hash', 'N/A')}`
- **区块号**: {tx_data.get('block_number', 'N/A')}
- **Gas 使用**: {tx_data.get('gas_used', 0):,}
- **状态**: {'成功' if tx_data.get('status') == 1 else '失败'}

### 运行时指标

- **调用深度**: {tx_data.get('call_depth', 0)}
- **重入深度**: {tx_data.get('reentrancy_depth', 0)}
- **循环迭代**: {tx_data.get('loop_iterations', 0)}

### 余额变化

"""

        balance_changes = tx_data.get('balance_changes', {})
        if balance_changes:
            for addr, change in balance_changes.items():
                change_rate = change.get('change_rate', 0)
                if change_rate != 0:
                    report += f"- `{addr[:10]}...`: {change_rate:+.4f}%\n"
        else:
            report += "无余额变化记录\n"

        report += """
---

## 📁 相关文件

- **攻击状态**: `{}`
- **不变量定义**: `{}`
- **Monitor 输出**: `{}`

---

*本报告由自动化验证脚本生成*
""".format(self.attack_state_file, self.invariants_file, self.monitor_output)

        return report

    def _print_summary(self, violations: List[Dict]):
        """打印结果摘要"""
        print("\n" + "=" * 80)
        print("验证完成！")
        print("=" * 80)

        if violations:
            print(f"\n⚠️  检测到 {len(violations)} 个不变量违规:")
            for v in violations:
                print(f"  - {v['invariant_id']}: {v['description'][:60]}...")
        else:
            print("\n✅ 未检测到不变量违规")

        print(f"\n📊 详细报告: {self.report_file}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description='端到端攻击验证 + 不变量检测',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 验证 BarleyFinance 攻击
  python src/test/verify_attack_with_invariants.py \\
    --event-name BarleyFinance_exp \\
    --year-month 2024-01

  # 使用自定义 RPC
  python src/test/verify_attack_with_invariants.py \\
    --event-name BarleyFinance_exp \\
    --year-month 2024-01 \\
    --rpc-url http://localhost:9545
        """
    )

    parser.add_argument('--event-name', required=True, help='事件名称 (如 BarleyFinance_exp)')
    parser.add_argument('--year-month', required=True, help='年月 (如 2024-01)')
    parser.add_argument('--rpc-url', default='http://localhost:8545', help='Anvil RPC URL')
    parser.add_argument('--use-fork', action='store_true', help='使用 fork 模式（fork 主网而非空白 Anvil）')
    parser.add_argument('--debug', action='store_true', help='启用调试日志')

    args = parser.parse_args()

    # 配置日志
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')

    # 创建验证器并执行
    verifier = AttackVerifier(args.event_name, args.year_month, args.rpc_url, use_fork=args.use_fork)
    success = verifier.verify()

    exit(0 if success else 1)


if __name__ == "__main__":
    main()
