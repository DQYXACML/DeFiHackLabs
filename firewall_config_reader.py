#!/usr/bin/env python3
"""
防火墙配置读取模块

功能：
1. 从firewall integration CLI生成的配置中提取被保护合约和函数信息
2. 支持多种配置文件格式（constraint_rules_v2.json优先）
3. 提供统一的接口给V2.5约束提取器使用

作者: Claude Code
版本: 1.0.0
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class ProtectedContract:
    """被保护的合约信息"""
    address: str
    name: Optional[str] = None

@dataclass
class ProtectedFunction:
    """被保护的函数信息"""
    contract_address: str
    function: str
    contract_name: Optional[str] = None
    signature: Optional[str] = None
    selector: Optional[str] = None

@dataclass
class FirewallConfig:
    """防火墙配置"""
    protocol: str
    year_month: str
    protected_contracts: List[ProtectedContract]
    protected_functions: List[ProtectedFunction]
    source: str  # 配置来源：constraint_rules_v2, firewall_env等

    def get_contract_addresses(self) -> Set[str]:
        """获取所有被保护合约地址（小写）"""
        return {c.address.lower() for c in self.protected_contracts}

    def get_function_names(self) -> Set[str]:
        """获取所有被保护函数名"""
        return {f.function for f in self.protected_functions}

    def get_functions_for_contract(self, contract_address: str) -> List[ProtectedFunction]:
        """获取特定合约的被保护函数列表"""
        addr_lower = contract_address.lower()
        return [f for f in self.protected_functions
                if f.contract_address.lower() == addr_lower]


class FirewallConfigReader:
    """防火墙配置读取器"""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.logger = logging.getLogger(__name__ + '.FirewallConfigReader')

    def load_config(self, protocol: str, year_month: str) -> Optional[FirewallConfig]:
        """
        加载防火墙配置

        Args:
            protocol: 协议名（如 BarleyFinance_exp）
            year_month: 年月（如 2024-01）

        Returns:
            FirewallConfig 或 None
        """
        # 尝试多个配置源，按优先级
        # 最高优先级：firewall_injection_record.json（来自批量注入）
        loaders = [
            self._load_from_injection_record,
            self._load_from_constraint_rules_v2,
            self._load_from_solved_constraints,
            self._load_from_invariants,
        ]

        for loader in loaders:
            try:
                config = loader(protocol, year_month)
                if config and config.protected_contracts:
                    self.logger.info(f"  ✓ 从 {config.source} 加载防火墙配置")
                    self.logger.info(f"    被保护合约: {len(config.protected_contracts)} 个")
                    self.logger.info(f"    被保护函数: {len(config.protected_functions)} 个")
                    return config
            except Exception as e:
                self.logger.debug(f"  尝试加载器 {loader.__name__} 失败: {e}")
                continue

        self.logger.warning(f"  未找到 {protocol}/{year_month} 的防火墙配置")
        return None

    def _load_from_injection_record(self, protocol: str, year_month: str) -> Optional[FirewallConfig]:
        """
        从 firewall_injection_record.json 加载配置（最高优先级）

        这是由批量注入工具自动生成的记录，包含：
        - main_contract.address: 被保护合约的地址
        - main_contract.actual_contract_name: 实际合约名称
        - injected_contracts[].file: 注入的文件名
        - injected_contracts[].functions: 注入的函数列表
        """
        config_file = self.project_root / 'extracted_contracts' / year_month / protocol / 'firewall_injection_record.json'

        if not config_file.exists():
            return None

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 检查必需字段
        main_contract = data.get('main_contract', {})
        if not main_contract or not main_contract.get('address'):
            self.logger.debug(f"  firewall_injection_record.json 中没有 main_contract 信息")
            return None

        injected_contracts = data.get('injected_contracts', [])
        if not injected_contracts:
            self.logger.debug(f"  firewall_injection_record.json 中没有 injected_contracts 信息")
            return None

        # 提取被保护合约
        protected_contracts = [
            ProtectedContract(
                address=main_contract['address'],
                name=main_contract.get('actual_contract_name') or main_contract.get('name')
            )
        ]

        # 提取被保护函数
        protected_functions = []
        contract_address = main_contract['address']
        contract_name = main_contract.get('actual_contract_name') or main_contract.get('name')

        for contract_info in injected_contracts:
            for func_name in contract_info.get('functions', []):
                func = ProtectedFunction(
                    contract_address=contract_address,
                    contract_name=contract_name,
                    function=func_name,
                    # signature 和 selector 在这个文件中没有，后续可以通过分析获取
                    signature=None,
                    selector=None
                )
                protected_functions.append(func)

        return FirewallConfig(
            protocol=protocol,
            year_month=year_month,
            protected_contracts=protected_contracts,
            protected_functions=protected_functions,
            source='firewall_injection_record.json'
        )

    def _load_from_constraint_rules_v2(self, protocol: str, year_month: str) -> Optional[FirewallConfig]:
        """
        从 constraint_rules_v2.json 加载配置

        这是最准确的配置源，包含：
        - vulnerable_contract: 被保护合约的地址和名称
        - constraints[].function: 被保护的函数名
        - constraints[].signature: 完整函数签名
        """
        config_file = self.project_root / 'extracted_contracts' / year_month / protocol / 'constraint_rules_v2.json'

        if not config_file.exists():
            return None

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 提取被保护合约
        vuln_contract = data.get('vulnerable_contract', {})
        if not vuln_contract or not vuln_contract.get('address'):
            self.logger.debug(f"  constraint_rules_v2.json 中没有 vulnerable_contract 信息")
            return None

        protected_contracts = [
            ProtectedContract(
                address=vuln_contract['address'],
                name=vuln_contract.get('name')
            )
        ]

        # 提取被保护函数
        protected_functions = []
        for constraint in data.get('constraints', []):
            func = ProtectedFunction(
                contract_address=vuln_contract['address'],
                contract_name=vuln_contract.get('name'),
                function=constraint.get('function', ''),
                signature=constraint.get('signature'),
                selector=constraint.get('selector')
            )
            protected_functions.append(func)

        return FirewallConfig(
            protocol=protocol,
            year_month=year_month,
            protected_contracts=protected_contracts,
            protected_functions=protected_functions,
            source='constraint_rules_v2.json'
        )

    def _load_from_solved_constraints(self, protocol: str, year_month: str) -> Optional[FirewallConfig]:
        """从 solved_constraints.json 加载配置"""
        config_file = self.project_root / 'extracted_contracts' / year_month / protocol / 'solved_constraints.json'

        if not config_file.exists():
            return None

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        vuln_contract = data.get('vulnerable_contract', {})
        if not vuln_contract or not vuln_contract.get('address'):
            return None

        protected_contracts = [
            ProtectedContract(
                address=vuln_contract['address'],
                name=vuln_contract.get('name')
            )
        ]

        protected_functions = []
        for constraint in data.get('solved_constraints', []):
            func = ProtectedFunction(
                contract_address=vuln_contract['address'],
                contract_name=vuln_contract.get('name'),
                function=constraint.get('function', ''),
                signature=constraint.get('signature')
            )
            protected_functions.append(func)

        return FirewallConfig(
            protocol=protocol,
            year_month=year_month,
            protected_contracts=protected_contracts,
            protected_functions=protected_functions,
            source='solved_constraints.json'
        )

    def _load_from_invariants(self, protocol: str, year_month: str) -> Optional[FirewallConfig]:
        """
        从 invariants_v2.json 加载配置

        从不变量定义中提取需要保护的合约列表
        """
        config_file = self.project_root / 'extracted_contracts' / year_month / protocol / 'invariants_v2.json'

        if not config_file.exists():
            return None

        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 从storage_invariants中提取合约
        protected_contracts_set = set()

        # invariants_v2.json 的结构可能是 {"invariants": [...], ...}
        invariants = data.get('invariants', [])

        for inv in invariants:
            # 尝试从不同的字段提取合约地址
            contracts = inv.get('contracts', [])
            for addr in contracts:
                if addr and addr.startswith('0x'):
                    protected_contracts_set.add(addr.lower())

            # 也尝试从 contract_address 字段提取
            contract_addr = inv.get('contract_address')
            if contract_addr and contract_addr.startswith('0x'):
                protected_contracts_set.add(contract_addr.lower())

        if not protected_contracts_set:
            return None

        protected_contracts = [
            ProtectedContract(address=addr)
            for addr in protected_contracts_set
        ]

        return FirewallConfig(
            protocol=protocol,
            year_month=year_month,
            protected_contracts=protected_contracts,
            protected_functions=[],  # invariants_v2.json 不包含函数级信息
            source='invariants_v2.json'
        )

    def get_analysis_targets(self, protocol: str, year_month: str) -> Optional[Dict]:
        """
        获取约束分析目标（简化接口）

        Returns:
            {
                "contract_addresses": ["0x04c80...", ...],  # 需要分析的合约地址
                "function_names": ["flash", "bond", ...],   # 需要分析的函数名
                "config": FirewallConfig                    # 完整配置对象
            }
        """
        config = self.load_config(protocol, year_month)
        if not config:
            return None

        return {
            "contract_addresses": list(config.get_contract_addresses()),
            "function_names": list(config.get_function_names()),
            "config": config
        }


# 使用示例
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    reader = FirewallConfigReader(Path(__file__).parent)

    # 测试BarleyFinance_exp
    targets = reader.get_analysis_targets('BarleyFinance_exp', '2024-01')
    if targets:
        print(f"\n被保护合约: {targets['contract_addresses']}")
        print(f"被保护函数: {targets['function_names']}")
        print(f"\n完整配置:")
        print(json.dumps(asdict(targets['config']), indent=2, ensure_ascii=False))
