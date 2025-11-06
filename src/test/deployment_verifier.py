#!/usr/bin/env python3
"""
部署验证工具

验证 Anvil 上部署的合约状态是否与 attack_state.json 一致
"""

import json
import logging
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
from web3 import Web3

logger = logging.getLogger(__name__)


class DeploymentVerifier:
    """部署验证器"""

    def __init__(self, rpc_url: str):
        """
        初始化验证器

        Args:
            rpc_url: Anvil RPC URL
        """
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise RuntimeError(f"无法连接到 {rpc_url}")

    def verify(self, attack_state_file: Path, sample_storage: int = 5) -> Tuple[bool, List[str]]:
        """
        验证部署状态

        Args:
            attack_state_file: attack_state.json 文件路径
            sample_storage: 抽样检查的存储槽数量

        Returns:
            (是否通过, 错误列表)
        """
        # 读取预期状态
        with open(attack_state_file) as f:
            expected = json.load(f)

        errors = []
        addresses = expected.get('addresses', {})

        logger.info(f"开始验证 {len(addresses)} 个地址...")

        for addr, data in addresses.items():
            addr_checksum = Web3.to_checksum_address(addr)

            # 验证代码
            code_errors = self._verify_code(addr_checksum, data)
            errors.extend(code_errors)

            # 验证余额
            balance_errors = self._verify_balance(addr_checksum, data)
            errors.extend(balance_errors)

            # 验证存储（抽样）
            storage_errors = self._verify_storage(addr_checksum, data, sample_storage)
            errors.extend(storage_errors)

            # 验证 nonce (EOA)
            if not data.get('is_contract', False):
                nonce_errors = self._verify_nonce(addr_checksum, data)
                errors.extend(nonce_errors)

        if errors:
            logger.error(f"❌ 验证失败，发现 {len(errors)} 个错误")
            return False, errors
        else:
            logger.info(f"✓ 验证通过，所有 {len(addresses)} 个地址状态一致")
            return True, []

    def _verify_code(self, addr: str, expected_data: Dict) -> List[str]:
        """验证合约代码"""
        errors = []
        expected_code = expected_data.get('code', '')

        # 空代码表示 EOA
        if not expected_code or expected_code == '0x':
            return errors

        actual_code = self.w3.eth.get_code(addr).hex()

        if actual_code.lower() != expected_code.lower():
            errors.append(f"{addr}: 代码不匹配 (预期 {len(expected_code)} 字节, 实际 {len(actual_code)} 字节)")
            logger.debug(f"  预期: {expected_code[:100]}...")
            logger.debug(f"  实际: {actual_code[:100]}...")

        return errors

    def _verify_balance(self, addr: str, expected_data: Dict) -> List[str]:
        """验证 ETH 余额"""
        errors = []
        expected_balance = int(expected_data.get('balance_wei', '0'))
        actual_balance = self.w3.eth.get_balance(addr)

        if actual_balance != expected_balance:
            errors.append(
                f"{addr}: 余额不匹配 (预期 {expected_balance} wei, 实际 {actual_balance} wei)"
            )

        return errors

    def _verify_storage(self, addr: str, expected_data: Dict, sample_size: int) -> List[str]:
        """验证存储槽（抽样检查）"""
        errors = []
        expected_storage = expected_data.get('storage', {})

        if not expected_storage:
            return errors

        # 抽样检查前 N 个存储槽
        sampled_slots = list(expected_storage.items())[:sample_size]

        for slot_str, expected_value in sampled_slots:
            slot = int(slot_str)
            actual_value = self.w3.eth.get_storage_at(addr, slot).hex()

            # 标准化格式 (统一为 0x 开头的 66 字符)
            expected_value_normalized = self._normalize_storage_value(expected_value)
            actual_value_normalized = self._normalize_storage_value(actual_value)

            if actual_value_normalized.lower() != expected_value_normalized.lower():
                errors.append(
                    f"{addr}[slot {slot}]: 存储不匹配\n"
                    f"  预期: {expected_value_normalized}\n"
                    f"  实际: {actual_value_normalized}"
                )

        return errors

    def _verify_nonce(self, addr: str, expected_data: Dict) -> List[str]:
        """验证 nonce (仅 EOA)"""
        errors = []
        expected_nonce = expected_data.get('nonce', 0)
        actual_nonce = self.w3.eth.get_transaction_count(addr)

        if actual_nonce != expected_nonce:
            errors.append(
                f"{addr}: nonce 不匹配 (预期 {expected_nonce}, 实际 {actual_nonce})"
            )

        return errors

    @staticmethod
    def _normalize_storage_value(value: str) -> str:
        """标准化存储值格式"""
        if not value:
            return '0x' + '0' * 64

        # 移除 0x 前缀
        if value.startswith('0x'):
            value = value[2:]

        # 补齐到 64 字符
        value = value.zfill(64)

        return '0x' + value


def verify_deployment(event_name: str, year_month: str, rpc_url: str) -> bool:
    """
    验证部署

    Args:
        event_name: 事件名称 (如 BarleyFinance_exp)
        year_month: 年月 (如 2024-01)
        rpc_url: Anvil RPC URL

    Returns:
        是否验证通过
    """
    attack_state_file = Path(f"extracted_contracts/{year_month}/{event_name}/attack_state.json")

    if not attack_state_file.exists():
        logger.error(f"未找到 attack_state.json: {attack_state_file}")
        return False

    verifier = DeploymentVerifier(rpc_url)
    passed, errors = verifier.verify(attack_state_file)

    if not passed:
        print("\n❌ 部署验证失败:")
        for err in errors:
            print(f"  {err}")
        return False

    print("\n✓ 部署验证通过")
    return True


def main():
    parser = argparse.ArgumentParser(description='验证 Anvil 部署状态')
    parser.add_argument('--event-name', required=True, help='事件名称 (如 BarleyFinance_exp)')
    parser.add_argument('--year-month', required=True, help='年月 (如 2024-01)')
    parser.add_argument('--rpc-url', default='http://localhost:8545', help='Anvil RPC URL')
    parser.add_argument('--debug', action='store_true', help='启用调试日志')

    args = parser.parse_args()

    # 配置日志
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')

    # 验证部署
    success = verify_deployment(args.event_name, args.year_month, args.rpc_url)
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
