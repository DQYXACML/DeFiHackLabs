#!/usr/bin/env python3
"""
约束求解器 (Constraint Solver)

基于阶段1提取的约束规则，结合真实Storage值进行求解，
生成具体的检测阈值和Fuzzing种子。

作者: FirewallOnchain Team
版本: 1.0.0
日期: 2025-01-21

使用示例:
    # 单个协议
    python solve_constraints.py \
        --protocol BarleyFinance_exp \
        --year-month 2024-01

    # 批量处理
    python solve_constraints.py \
        --batch \
        --filter 2024-01
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal, getcontext

# 设置高精度计算
getcontext().prec = 78  # uint256最大位数

# 配置日志
class Logger:
    """简单的彩色日志器"""
    COLORS = {
        'info': '\033[0;34m',     # 蓝色
        'success': '\033[0;32m',  # 绿色
        'warning': '\033[1;33m',  # 黄色
        'error': '\033[0;31m',    # 红色
        'reset': '\033[0m'
    }

    @staticmethod
    def info(msg):
        print(f"{Logger.COLORS['info']}[INFO]{Logger.COLORS['reset']} {msg}")

    @staticmethod
    def success(msg):
        print(f"{Logger.COLORS['success']}[SUCCESS]{Logger.COLORS['reset']} {msg}")

    @staticmethod
    def warning(msg):
        print(f"{Logger.COLORS['warning']}[WARNING]{Logger.COLORS['reset']} {msg}")

    @staticmethod
    def error(msg):
        print(f"{Logger.COLORS['error']}[ERROR]{Logger.COLORS['reset']} {msg}")

logger = Logger()


class StorageValueResolver:
    """
    Storage值解析器 - 从attack_state.json读取真实slot值

    支持:
    1. 固定slot (如 0x2, 0x3)
    2. 动态slot (mapping的keccak256计算)
    3. ERC20 balanceOf 特殊处理
    """

    def __init__(self, protocol_dir: Path):
        self.protocol_dir = protocol_dir
        self.attack_state = self._load_attack_state()

    def _load_attack_state(self) -> Optional[Dict]:
        """加载attack_state.json"""
        state_path = self.protocol_dir / "attack_state.json"
        if not state_path.exists():
            return None

        with open(state_path, 'r') as f:
            return json.load(f)

    def get_storage_value(self, contract_address: str, slot: str) -> Optional[int]:
        """
        获取指定合约的storage slot值

        Args:
            contract_address: 合约地址 (自动处理大小写)
            slot: slot标识 (支持 "0x2", "2", "dynamic")

        Returns:
            slot值 (int) 或 None
        """
        if not self.attack_state:
            return None

        # 查找合约
        addresses = self.attack_state.get('addresses', {})
        contract_data = None

        for addr_key, data in addresses.items():
            if addr_key.lower() == contract_address.lower():
                contract_data = data
                break

        if not contract_data:
            return None

        storage = contract_data.get('storage', {})

        # 处理slot格式
        if slot == "dynamic":
            # 动态slot暂时返回None，需要更多上下文
            return None

        # 标准化slot key
        slot_key = self._normalize_slot_key(slot)

        # 查找slot值
        for key, value in storage.items():
            if self._normalize_slot_key(key) == slot_key:
                return self._hex_to_int(value)

        return None

    def get_erc20_balance(self, token_address: str, holder_address: str) -> Optional[int]:
        """
        获取ERC20代币余额

        Args:
            token_address: 代币合约地址
            holder_address: 持有者地址

        Returns:
            余额 (int) 或 None
        """
        if not self.attack_state:
            return None

        addresses = self.attack_state.get('addresses', {})

        for addr_key, data in addresses.items():
            if addr_key.lower() == token_address.lower():
                erc20_balances = data.get('erc20_balances', {})
                for holder, balance in erc20_balances.items():
                    if holder.lower() == holder_address.lower():
                        return int(balance)

        return None

    def get_contract_eth_balance(self, contract_address: str) -> Optional[int]:
        """获取合约ETH余额"""
        if not self.attack_state:
            return None

        addresses = self.attack_state.get('addresses', {})

        for addr_key, data in addresses.items():
            if addr_key.lower() == contract_address.lower():
                balance_wei = data.get('balance_wei', '0')
                return int(balance_wei)

        return None

    def _normalize_slot_key(self, slot: str) -> str:
        """标准化slot key为十进制字符串"""
        slot = str(slot).strip()

        if slot.startswith('0x'):
            return str(int(slot, 16))
        else:
            try:
                return str(int(slot))
            except ValueError:
                return slot

    def _hex_to_int(self, hex_value: str) -> int:
        """将hex字符串转为int"""
        if hex_value.startswith('0x'):
            return int(hex_value, 16)
        else:
            # 假设是没有0x前缀的hex
            try:
                return int(hex_value, 16)
            except ValueError:
                return int(hex_value)


class ConstraintExpressionSolver:
    """
    约束表达式求解器

    解析并计算约束表达式，如:
    - "amount > totalSupply * 0.5"
    - "amount > availableLiquidity * 0.8"
    """

    # 常见的状态变量到slot的默认映射
    DEFAULT_SLOT_MAPPING = {
        'totalSupply': '0x2',
        'totalLiquidity': '0x3',
        'availableLiquidity': '0x4',
        'reserve': '0x5',
        'poolBalance': '0x6',
    }

    def __init__(self, storage_resolver: StorageValueResolver):
        self.storage_resolver = storage_resolver

    def solve(self, constraint: Dict, contract_address: str) -> Dict:
        """
        求解约束，返回具体的阈值

        Args:
            constraint: 约束字典
            contract_address: 被攻击合约地址

        Returns:
            {
                "resolved": True/False,
                "threshold": 具体阈值,
                "state_value": 状态变量值,
                "coefficient": 系数,
                "expression": "原始表达式",
                "resolved_expression": "解析后的表达式"
            }
        """
        result = {
            "resolved": False,
            "threshold": None,
            "state_value": None,
            "coefficient": None,
            "expression": constraint.get("expression", ""),
            "resolved_expression": None
        }

        danger_condition = constraint.get("danger_condition", "")
        variables = constraint.get("variables", {})

        if not danger_condition or not variables:
            return result

        # 识别状态变量和系数
        state_var_name, coefficient = self._parse_condition(danger_condition)

        if not state_var_name:
            return result

        # 获取状态变量信息
        state_var_info = None
        for var_name, var_info in variables.items():
            if var_info.get("source") == "storage":
                state_var_name = var_info.get("semantic_name", var_name)
                state_var_info = var_info
                break

        if not state_var_info:
            return result

        # 解析slot
        slot = state_var_info.get("slot", "")

        # 如果slot是dynamic，尝试使用默认映射
        if slot == "dynamic":
            semantic_name = state_var_info.get("semantic_name", "")
            # 尝试从默认映射获取
            for key, default_slot in self.DEFAULT_SLOT_MAPPING.items():
                if key.lower() in semantic_name.lower():
                    slot = default_slot
                    break

        # 获取storage值
        state_value = self.storage_resolver.get_storage_value(contract_address, slot)

        if state_value is None:
            # 尝试备用策略
            semantic_name = state_var_info.get("semantic_name", state_var_name).lower()

            # 策略1: 从ERC20余额获取totalSupply
            if "supply" in semantic_name:
                state_value = self._estimate_total_supply(contract_address)

            # 策略2: liquidity通常是底层代币在合约中的余额
            elif "liquidity" in semantic_name or "reserve" in semantic_name:
                state_value = self._estimate_liquidity(contract_address)

            # 策略3: poolBalance - 尝试获取合约的代币余额
            elif "poolbalance" in semantic_name or "pool" in semantic_name:
                state_value = self._estimate_pool_balance(contract_address)

            # 策略4: userBalance/balanceOf - 从攻击参数推断
            elif "balance" in semantic_name or "userbalance" in semantic_name:
                amount_info = variables.get("amount", {})
                value_expr = amount_info.get("value_expr", "")
                state_value = self._estimate_from_value_expr(value_expr, contract_address)

            # 策略5: userCollateral/userBorrowPart - 使用攻击参数值
            elif any(kw in semantic_name for kw in ["collateral", "borrow", "debt", "share"]):
                amount_info = variables.get("amount", {})
                value_expr = amount_info.get("value_expr", "")
                state_value = self._estimate_from_value_expr(value_expr, contract_address)

            # 策略6: 使用攻击参数的value_expr推断 (通用)
            if state_value is None:
                amount_info = variables.get("amount", {})
                value_expr = amount_info.get("value_expr", "")
                state_value = self._estimate_from_value_expr(value_expr, contract_address)

            # 策略7: 扫描所有storage找到最大值作为totalSupply
            if state_value is None and "supply" in semantic_name:
                state_value = self._find_max_storage_value(contract_address)

        if state_value is None:
            return result

        # 计算阈值
        threshold = int(Decimal(str(state_value)) * Decimal(str(coefficient)))

        result["resolved"] = True
        result["threshold"] = threshold
        result["state_value"] = state_value
        result["coefficient"] = coefficient
        result["resolved_expression"] = f"amount > {threshold}"

        return result

    def _parse_condition(self, condition: str) -> Tuple[Optional[str], float]:
        """
        解析条件表达式，提取状态变量名和系数

        Args:
            condition: 如 "amount > totalSupply * 0.5"

        Returns:
            (状态变量名, 系数)
        """
        # 匹配 "param > stateVar * coefficient" 模式
        pattern = r'\w+\s*>\s*(\w+)\s*\*\s*([\d.]+)'
        match = re.search(pattern, condition)

        if match:
            state_var = match.group(1)
            coefficient = float(match.group(2))
            return (state_var, coefficient)

        # 匹配 "param > stateVar" 模式 (系数为1)
        pattern = r'\w+\s*>\s*(\w+)$'
        match = re.search(pattern, condition.strip())

        if match:
            state_var = match.group(1)
            return (state_var, 1.0)

        return (None, 0.0)

    def _estimate_total_supply(self, contract_address: str) -> Optional[int]:
        """
        估算totalSupply - 通过合约storage或ERC20余额推断
        """
        # 尝试slot 2 (ERC20标准)
        value = self.storage_resolver.get_storage_value(contract_address, "2")
        if value and value > 0:
            return value

        return None

    def _estimate_liquidity(self, contract_address: str) -> Optional[int]:
        """
        估算流动性 - 通常是底层代币在合约中的余额

        对于BarleyFinance，liquidity = BARL.balanceOf(wBARL)
        """
        if not self.storage_resolver.attack_state:
            return None

        addresses = self.storage_resolver.attack_state.get('addresses', {})

        # 查找合约地址
        contract_lower = contract_address.lower()

        # 遍历所有代币，查找在目标合约中有余额的
        for addr_key, data in addresses.items():
            erc20_balances = data.get('erc20_balances', {})

            for holder, balance in erc20_balances.items():
                if holder.lower() == contract_lower:
                    balance_int = int(balance)
                    if balance_int > 0:
                        return balance_int

        return None

    def _estimate_from_value_expr(self, value_expr: str, contract_address: str) -> Optional[int]:
        """
        从value_expr推断状态值

        支持的模式:
        1. Token.balanceOf(address(Contract)) - 单参数balanceOf
        2. DegenBox.balanceOf(address(Token), address(Contract)) - 双参数balanceOf
        3. 数字字面量 - 直接使用（作为当前余额估计）
        4. 算术表达式 - 提取数字部分
        """
        if not value_expr:
            return None

        value_expr = value_expr.strip()

        # 模式0: 变量名 (如 "amountToBorrow", "depositAmount")
        # 这些是代码中的变量引用，无法直接求解，使用默认值
        if value_expr.isidentifier() and not value_expr.isdigit():
            # 返回一个合理的默认值
            return 10**18  # 1个token (18位小数)

        # 模式1: 数字字面量 (如 "1", "100", "0")
        # 对于userBalance约束，数字表示攻击时的实际金额
        if value_expr.isdigit():
            val = int(value_expr)
            if val == 0:
                # 零值可能表示提取所有，使用默认值
                return 10**18
            elif val > 0:
                # 使用合理的默认值：假设这是最小操作量，实际余额可能更大
                return max(val * 1000, 10**18)  # 至少1个token (18位小数)

        # 模式2: 算术表达式 (如 "depositAmount - 100", "((amount * 3) >> 1) - 1")
        # 尝试提取其中的数字
        numbers = re.findall(r'\d+', value_expr)
        if numbers and not '.balanceOf' in value_expr:
            # 算术表达式，取最大的数字作为估计
            max_num = max(int(n) for n in numbers)
            if max_num > 0:
                return max(max_num * 1000, 10**18)

        # 模式3: 单参数balanceOf - Token.balanceOf(address(Contract))
        pattern = r'(\w+)\.balanceOf\(address\((\w+)\)\)'
        match = re.search(pattern, value_expr)
        if match:
            return self._resolve_single_balance_of(match.group(1), match.group(2))

        # 模式4: 双参数balanceOf - DegenBox.balanceOf(address(Token), address(Contract))
        pattern = r'(\w+)\.balanceOf\(address\((\w+)\),\s*address\((\w+)\)\)'
        match = re.search(pattern, value_expr)
        if match:
            return self._resolve_double_balance_of(match.group(1), match.group(2), match.group(3))

        return None

    def _resolve_single_balance_of(self, token_name: str, holder_name: str) -> Optional[int]:
        """解析单参数balanceOf"""
        if not self.storage_resolver.attack_state:
            return None

        addresses = self.storage_resolver.attack_state.get('addresses', {})

        # 查找token和holder地址
        token_address = None
        holder_address = None

        for addr_key, data in addresses.items():
            name = data.get('name', '')
            # 精确匹配或包含匹配
            if name == token_name or token_name in name or name in token_name:
                token_address = addr_key
            # holder可能有多种名称 (如 SoulMateContract -> Victim)
            if name == holder_name or holder_name in name or name in holder_name:
                holder_address = addr_key
            # 特殊处理: Victim/Vuln通常是目标合约
            if holder_address is None and name in ['Victim', 'Vuln', 'Vulnerable']:
                holder_address = addr_key

        if token_address and holder_address:
            token_data = addresses.get(token_address, {})
            erc20_balances = token_data.get('erc20_balances', {})

            for holder, balance in erc20_balances.items():
                if holder.lower() == holder_address.lower():
                    return int(balance)

        # 如果找不到，尝试在所有token中查找holder
        if token_address is None and holder_address:
            for addr_key, data in addresses.items():
                erc20_balances = data.get('erc20_balances', {})
                for holder, balance in erc20_balances.items():
                    if holder.lower() == holder_address.lower():
                        bal = int(balance)
                        if bal > 0:
                            return bal

        # 最后的备用策略：如果token找到了但holder找不到，
        # 返回该token所有持有者中最大的余额作为估计
        if token_address:
            token_data = addresses.get(token_address, {})
            erc20_balances = token_data.get('erc20_balances', {})
            if erc20_balances:
                max_balance = max(int(b) for b in erc20_balances.values())
                if max_balance > 0:
                    return max_balance

        return None

    def _resolve_double_balance_of(self, vault_name: str, token_name: str, holder_name: str) -> Optional[int]:
        """
        解析双参数balanceOf (如DegenBox的share机制)

        DegenBox.balanceOf(address(MIM), address(CauldronV4))
        表示CauldronV4在DegenBox中持有的MIM份额
        """
        if not self.storage_resolver.attack_state:
            return None

        addresses = self.storage_resolver.attack_state.get('addresses', {})

        # 对于这种复杂的Vault系统，尝试查找相关的ERC20余额
        # 简化处理：查找token在holder中的余额
        return self._resolve_single_balance_of(token_name, holder_name)

    def _estimate_pool_balance(self, contract_address: str) -> Optional[int]:
        """
        估算池子余额 - 通常是代币在合约中的余额
        """
        return self._estimate_liquidity(contract_address)

    def _find_max_storage_value(self, contract_address: str) -> Optional[int]:
        """
        扫描所有storage，找到最大的合理值作为totalSupply

        策略：找到小于1e30的最大值（排除地址等非数值存储）
        """
        if not self.storage_resolver.attack_state:
            return None

        addresses = self.storage_resolver.attack_state.get('addresses', {})

        for addr_key, data in addresses.items():
            if addr_key.lower() == contract_address.lower():
                storage = data.get('storage', {})

                max_value = 0
                for slot, value in storage.items():
                    try:
                        int_value = int(value, 16) if isinstance(value, str) else int(value)
                        # 排除地址类型（通常前12字节为0）和过大的值
                        if int_value > max_value and int_value < 10**30:
                            # 排除看起来像地址的值
                            hex_str = hex(int_value)
                            if not (len(hex_str) == 42 and hex_str.startswith('0x')):
                                max_value = int_value
                    except:
                        continue

                if max_value > 0:
                    return max_value

        return None


class FuzzingSeedGenerator:
    """
    Fuzzing种子生成器

    基于约束边界生成测试参数，供Autopath的Fuzzer使用
    """

    def generate(self, solved_constraint: Dict, original_constraint: Dict) -> List[Dict]:
        """
        生成Fuzzing种子

        Args:
            solved_constraint: 求解后的约束
            original_constraint: 原始约束

        Returns:
            种子列表，每个种子包含:
            {
                "type": "boundary" | "safe" | "attack",
                "value": 具体值,
                "description": 描述
            }
        """
        seeds = []

        if not solved_constraint.get("resolved"):
            return seeds

        threshold = solved_constraint["threshold"]
        state_value = solved_constraint["state_value"]
        coefficient = solved_constraint["coefficient"]

        # 1. 边界值种子 (刚好触发)
        seeds.append({
            "type": "boundary",
            "value": threshold + 1,
            "description": f"刚好超过阈值 ({threshold}+1)"
        })

        # 2. 安全值种子 (远低于阈值)
        safe_coefficient = self._get_safe_coefficient(original_constraint)
        safe_value = int(Decimal(str(state_value)) * Decimal(str(safe_coefficient)))
        seeds.append({
            "type": "safe",
            "value": safe_value,
            "description": f"安全范围 ({safe_coefficient*100:.0f}%)"
        })

        # 3. 攻击值种子 (典型攻击大小)
        attack_value = int(Decimal(str(state_value)) * Decimal("0.95"))
        seeds.append({
            "type": "attack",
            "value": attack_value,
            "description": "典型攻击值 (95%)"
        })

        # 4. 极端值种子
        seeds.append({
            "type": "extreme",
            "value": state_value,
            "description": "完全耗尽 (100%)"
        })

        # 5. 零值种子 (边界测试)
        seeds.append({
            "type": "zero",
            "value": 0,
            "description": "零值边界"
        })

        return seeds

    def _get_safe_coefficient(self, constraint: Dict) -> float:
        """从safe_condition提取安全系数"""
        safe_condition = constraint.get("constraint", {}).get("safe_condition", "")

        # 解析 "amount <= stateVar * 0.1"
        pattern = r'\*\s*([\d.]+)'
        match = re.search(pattern, safe_condition)

        if match:
            return float(match.group(1))

        return 0.1  # 默认10%


class ParamCheckModuleFormatter:
    """
    ParamCheckModule格式转换器

    将求解结果转换为链上防火墙可用的规则格式
    """

    def format(self, solved_constraints: List[Dict], protocol_name: str) -> Dict:
        """
        格式化为ParamCheckModule规则

        Returns:
            {
                "protocol": "BarleyFinance_exp",
                "rules": [
                    {
                        "function_sig": "0x1234...",
                        "param_index": 1,
                        "rule_type": "RANGE",
                        "min_value": "0",
                        "max_value": "1000000...",
                        "description": "..."
                    }
                ]
            }
        """
        rules = []

        for item in solved_constraints:
            constraint = item.get("constraint", {})
            solved = item.get("solved", {})

            if not solved.get("resolved"):
                continue

            # 获取函数签名
            signature = item.get("signature", "")
            function_sig = self._compute_selector(signature)

            # 获取参数索引
            param_index = self._get_amount_param_index(constraint)

            # 创建规则
            rule = {
                "function_sig": function_sig,
                "function_name": item.get("function", ""),
                "param_index": param_index,
                "rule_type": "RANGE",
                "min_value": "0",
                "max_value": str(solved["threshold"]),
                "threshold": solved["threshold"],
                "state_value": solved["state_value"],
                "coefficient": solved["coefficient"],
                "attack_pattern": item.get("attack_pattern", ""),
                "description": constraint.get("constraint", {}).get("semantics", "")
            }

            rules.append(rule)

        return {
            "protocol": protocol_name,
            "version": "1.0.0",
            "rules": rules,
            "metadata": {
                "generated_by": "solve_constraints.py",
                "total_rules": len(rules)
            }
        }

    def _compute_selector(self, signature: str) -> str:
        """计算函数选择器 (简化版，实际应使用keccak256)"""
        import hashlib

        # 使用keccak256的前4字节
        # 注意：这里使用sha3_256模拟，实际应使用真正的keccak256
        try:
            from Crypto.Hash import keccak
            k = keccak.new(digest_bits=256)
            k.update(signature.encode())
            return "0x" + k.hexdigest()[:8]
        except ImportError:
            # 降级方案：使用hashlib
            h = hashlib.sha256(signature.encode())
            return "0x" + h.hexdigest()[:8]

    def _get_amount_param_index(self, constraint: Dict) -> int:
        """获取金额参数的索引"""
        variables = constraint.get("constraint", {}).get("variables", {})

        for var_name, var_info in variables.items():
            if var_info.get("source") == "function_parameter":
                return var_info.get("index", 0)

        return 0


class ConstraintSolver:
    """
    主求解器 - 协调各个组件
    """

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.extracted_dir = repo_root / "extracted_contracts"

    def solve_single(self, protocol_name: str, year_month: str) -> Optional[Dict]:
        """
        求解单个协议的约束

        Args:
            protocol_name: 协议名称
            year_month: 年月

        Returns:
            完整的求解结果
        """
        logger.info(f"开始求解约束: {protocol_name}")

        # 1. 加载约束规则
        protocol_dir = self.extracted_dir / year_month / protocol_name
        constraint_file = protocol_dir / "constraint_rules.json"

        if not constraint_file.exists():
            logger.warning(f"约束文件不存在: {constraint_file}")
            return None

        with open(constraint_file, 'r') as f:
            constraint_rules = json.load(f)

        constraints = constraint_rules.get("constraints", [])
        if not constraints:
            logger.warning(f"  无约束规则")
            return None

        # 2. 初始化组件
        storage_resolver = StorageValueResolver(protocol_dir)
        expr_solver = ConstraintExpressionSolver(storage_resolver)
        seed_generator = FuzzingSeedGenerator()
        formatter = ParamCheckModuleFormatter()

        # 3. 获取合约地址
        contract_address = constraint_rules.get("vulnerable_contract", {}).get("address", "")

        # 4. 求解每个约束
        solved_constraints = []
        total_resolved = 0

        for constraint in constraints:
            constraint_data = constraint.get("constraint", {})

            # 求解
            solved = expr_solver.solve(constraint_data, contract_address)

            # 生成种子
            seeds = []
            if solved["resolved"]:
                seeds = seed_generator.generate(solved, constraint)
                total_resolved += 1

            solved_constraints.append({
                "function": constraint.get("function", ""),
                "signature": constraint.get("signature", ""),
                "attack_pattern": constraint.get("attack_pattern", ""),
                "constraint": constraint,
                "solved": solved,
                "fuzzing_seeds": seeds
            })

        logger.info(f"  求解成功: {total_resolved}/{len(constraints)}")

        # 5. 格式化为ParamCheckModule规则
        param_check_rules = formatter.format(solved_constraints, protocol_name)

        # 6. 构建结果
        result = {
            "protocol": protocol_name,
            "year_month": year_month,
            "vulnerable_contract": constraint_rules.get("vulnerable_contract", {}),
            "solved_constraints": solved_constraints,
            "param_check_rules": param_check_rules,
            "summary": {
                "total_constraints": len(constraints),
                "resolved_constraints": total_resolved,
                "resolution_rate": f"{total_resolved/len(constraints)*100:.1f}%" if constraints else "0%"
            },
            "metadata": {
                "solver_version": "1.0.0",
                "generated_by": "solve_constraints.py"
            }
        }

        return result

    def save_result(self, result: Dict, protocol_name: str, year_month: str):
        """保存求解结果"""
        if not result:
            return

        output_path = self.extracted_dir / year_month / protocol_name / "solved_constraints.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)

        logger.success(f"求解结果已保存: {output_path}")

    def batch_solve(self, year_month_filter: str = None) -> Dict[str, Dict]:
        """批量求解"""
        results = {}

        # 扫描目录
        year_month_dirs = []
        if year_month_filter:
            filter_dir = self.extracted_dir / year_month_filter
            if filter_dir.exists():
                year_month_dirs = [filter_dir]
        else:
            year_month_dirs = [d for d in self.extracted_dir.iterdir() if d.is_dir()]

        for year_month_dir in year_month_dirs:
            year_month = year_month_dir.name

            for protocol_dir in year_month_dir.iterdir():
                if not protocol_dir.is_dir():
                    continue

                protocol_name = protocol_dir.name

                # 检查是否有约束文件
                constraint_file = protocol_dir / "constraint_rules.json"
                if not constraint_file.exists():
                    continue

                try:
                    result = self.solve_single(protocol_name, year_month)
                    if result:
                        self.save_result(result, protocol_name, year_month)
                        results[protocol_name] = result
                except Exception as e:
                    logger.error(f"处理 {protocol_name} 时出错: {e}")

        return results


def main():
    parser = argparse.ArgumentParser(
        description="约束求解器 - 将约束规则转换为具体检测阈值",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 单个协议
  python solve_constraints.py --protocol BarleyFinance_exp --year-month 2024-01

  # 批量处理2024-01的所有协议
  python solve_constraints.py --batch --filter 2024-01

  # 批量处理所有协议
  python solve_constraints.py --batch
        """
    )

    parser.add_argument(
        '--protocol',
        help='协议名称（如 BarleyFinance_exp）'
    )

    parser.add_argument(
        '--year-month',
        help='年月（如 2024-01）'
    )

    parser.add_argument(
        '--batch',
        action='store_true',
        help='批量处理模式'
    )

    parser.add_argument(
        '--filter',
        help='批量模式下的年月过滤器（如 2024-01）'
    )

    args = parser.parse_args()

    # 确定repo根目录
    script_dir = Path(__file__).parent
    repo_root = script_dir

    solver = ConstraintSolver(repo_root)

    if args.batch:
        # 批量模式
        logger.info("=== 批量求解模式 ===")
        results = solver.batch_solve(year_month_filter=args.filter)

        # 统计
        total_resolved = sum(
            r["summary"]["resolved_constraints"]
            for r in results.values()
        )
        total_constraints = sum(
            r["summary"]["total_constraints"]
            for r in results.values()
        )

        logger.success(f"\n总计处理: {len(results)} 个协议")
        logger.success(f"求解成功: {total_resolved}/{total_constraints} 个约束")

    elif args.protocol and args.year_month:
        # 单个协议模式
        logger.info("=== 单协议求解模式 ===")
        result = solver.solve_single(args.protocol, args.year_month)

        if result:
            solver.save_result(result, args.protocol, args.year_month)

            # 打印摘要
            print("\n--- 求解摘要 ---")
            for item in result["solved_constraints"]:
                solved = item["solved"]
                if solved["resolved"]:
                    print(f"✓ {item['function']}: threshold={solved['threshold']}")
                else:
                    print(f"✗ {item['function']}: 未求解")
        else:
            logger.error("求解失败")
            sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
