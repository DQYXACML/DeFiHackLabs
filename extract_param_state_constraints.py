#!/usr/bin/env python3
"""
参数-状态约束提取器 (Parameter-State Constraint Extractor)

从攻击PoC脚本中提取攻击参数与合约状态的约束关系。
这些约束用于指导后续的约束求解和targeted fuzzing。

作者: FirewallOnchain Team
版本: 1.0.0
日期: 2025-01-21

使用示例:
    # 单个协议
    python extract_param_state_constraints.py \\
        --protocol BarleyFinance_exp \\
        --year-month 2024-01

    # 批量处理
    python extract_param_state_constraints.py \\
        --batch \\
        --filter 2024-01
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

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


class AttackScriptParser:
    """攻击脚本解析器 - 识别关键函数调用和参数"""

    def __init__(self, script_path: Path):
        self.script_path = script_path
        self.script_content = script_path.read_text()

    def parse(self) -> Dict:
        """
        解析攻击脚本，提取关键信息

        Returns:
            {
                "vulnerable_contract": {"address": "0x...", "name": "wBARL"},
                "attack_calls": [
                    {
                        "function": "bond",
                        "signature": "bond(address,uint256)",
                        "parameters": {...},
                        "line_number": 90
                    }
                ],
                "loop_info": {"count": 20, "function": "flash"}
            }
        """
        result = {
            "vulnerable_contract": self._extract_vulnerable_contract(),
            "attack_calls": self._extract_attack_calls(),
            "loop_info": self._extract_loop_info()
        }
        return result

    def _extract_vulnerable_contract(self) -> Dict:
        """
        从注释中提取被攻击合约信息 (增强版 - 支持多种格式)

        支持的格式:
        1. // Vulnerable Contract : https://etherscan.io/address/0x...
        2. // Vuln Contract: https://etherscan.io/address/0x...
        3. - Vuln Contract: https://etherscan.io/address/0x...
        4. // Vulnerable Contract : 0x... (无URL)
        5. // Victim Contract : https://... (备用关键词)
        """
        # 定义多种匹配模式 (按优先级排序)
        patterns = [
            # 模式1: 标准格式 "Vulnerable Contract : https://...address/0x..."
            r'//\s*Vuln(?:erable)?\s+Contract\s*:\s*https?://[^/]+/address/(0x[a-fA-F0-9]{40})',

            # 模式2: Markdown格式 "- Vuln Contract: https://..."
            r'-\s*Vuln(?:erable)?\s+Contract\s*:\s*https?://[^/]+/address/(0x[a-fA-F0-9]{40})',

            # 模式3: 无URL格式 "Vulnerable Contract : 0x..."
            r'//\s*Vuln(?:erable)?\s+Contract\s*:\s*(0x[a-fA-F0-9]{40})',

            # 模式4: 备用关键词 "Victim Contract"
            r'//\s*Victim\s+Contract\s*:\s*https?://[^/]+/address/(0x[a-fA-F0-9]{40})',

            # 模式5: 宽松匹配 "Vulnerable: https://..."
            r'//\s*Vuln(?:erable)?\s*:\s*https?://[^/]+/address/(0x[a-fA-F0-9]{40})',
        ]

        # 尝试所有模式
        for pattern in patterns:
            match = re.search(pattern, self.script_content, re.IGNORECASE)
            if match:
                address = match.group(1)
                name = self._infer_contract_name(address)
                return {"address": address, "name": name}

        # 备用策略: 从接口定义推断
        # 查找类似 IVulnContract vuln = IVulnContract(0x...)
        interface_pattern = r'I(\w+)\s+\w+\s*=\s*I\w+\((0x[a-fA-F0-9]{40})\)'
        match = re.search(interface_pattern, self.script_content)
        if match:
            name = match.group(1)
            address = match.group(2)
            return {"address": address, "name": name}

        return {"address": None, "name": None}

    def _infer_contract_name(self, address: str) -> str:
        """
        从地址推断合约名称

        策略:
        1. 查找接口定义: ContractName = IContract(0x...)
        2. 查找address常量: address constant name = 0x...
        3. 查找变量定义: IContract contract = IContract(0x...)
        4. 从函数调用推断: vuln.someFunction(...)
        5. 返回"Unknown"
        """
        # 策略1: 接口定义 (最常见且可靠)
        # ContractName = IContractInterface(0x...)
        name_pattern1 = rf'(\w+)\s*=\s*I\w+\({address}\)'
        match = re.search(name_pattern1, self.script_content, re.IGNORECASE)
        if match:
            return match.group(1)

        # 策略2: address常量定义 (Gamma_exp使用此格式)
        # address constant uniproxy = 0x...
        name_pattern2 = rf'address\s+(?:constant|immutable)?\s*(\w+)\s*=\s*{address}'
        match = re.search(name_pattern2, self.script_content, re.IGNORECASE)
        if match:
            var_name = match.group(1)
            # 首字母大写
            return var_name[0].upper() + var_name[1:] if var_name else "Unknown"

        # 策略3: 接口类型声明
        # IVulnerableContract vuln = IVulnerableContract(0x...)
        name_pattern3 = rf'I(\w+)\s+\w+\s*=\s*I\w+\({address}\)'
        match = re.search(name_pattern3, self.script_content, re.IGNORECASE)
        if match:
            return match.group(1)

        # 策略4: 从函数调用中推断
        # 查找 varName.functionCall() 模式
        # 同时验证该地址在附近被使用
        call_pattern = rf'(\w+)\.\w+\('
        for match in re.finditer(call_pattern, self.script_content):
            var_name = match.group(1)
            # 在附近查找该地址
            context_start = max(0, match.start() - 500)
            context_end = min(len(self.script_content), match.end() + 500)
            context = self.script_content[context_start:context_end]
            if address.lower() in context.lower():
                # 首字母大写
                return var_name[0].upper() + var_name[1:] if var_name else "Unknown"

        return "Unknown"

    def _extract_attack_calls(self) -> List[Dict]:
        """
        提取对被攻击合约的函数调用

        识别模式:
        - wBARL.flash(...)
        - wBARL.bond(address(BARL), BARL.balanceOf(address(this)))
        - wBARL.debond(...)
        """
        calls = []
        vuln_contract = self._extract_vulnerable_contract()
        contract_name = vuln_contract.get("name", "")

        if not contract_name or contract_name == "Unknown":
            return calls

        # 匹配函数调用起始: contractName.functionName(
        pattern = rf'{contract_name}\.(\w+)\s*\('

        for line_no, line in enumerate(self.script_content.split('\n'), 1):
            # 跳过注释和接口定义
            if line.strip().startswith('//') or 'interface' in line:
                continue

            if contract_name not in line:
                continue

            # 查找所有函数调用起始位置
            for match in re.finditer(pattern, line):
                func_name = match.group(1)

                # 跳过ERC20标准函数（这些不是攻击特定函数）
                if func_name in ['balanceOf', 'allowance', 'approve', 'transfer', 'transferFrom', 'totalSupply']:
                    continue

                # 提取参数（处理任意嵌套括号）
                start_pos = match.end()
                params_str = self._extract_balanced_parens(line[start_pos:])

                # 解析参数
                params = self._parse_parameters(func_name, params_str)

                calls.append({
                    "function": func_name,
                    "signature": f"{func_name}({','.join([p['type'] for p in params])})",
                    "parameters": params,
                    "line_number": line_no,
                    "raw_call": f"{contract_name}.{func_name}(...)"
                })

        return calls

    def _extract_balanced_parens(self, text: str) -> str:
        """
        从文本中提取平衡的括号内容

        Args:
            text: 从'('之后开始的文本

        Returns:
            括号内的内容（不包括最外层括号）
        """
        depth = 1
        result = ""

        for char in text:
            if char == '(':
                depth += 1
                result += char
            elif char == ')':
                depth -= 1
                if depth == 0:
                    break
                result += char
            else:
                result += char

        return result.strip()

    def _parse_parameters(self, func_name: str, params_str: str) -> List[Dict]:
        """
        解析函数参数

        Args:
            func_name: 函数名
            params_str: 参数字符串，如 "address(BARL), BARL.balanceOf(address(this))"

        Returns:
            [
                {"index": 0, "type": "address", "value_expr": "address(BARL)", "is_dynamic": True},
                {"index": 1, "type": "uint256", "value_expr": "BARL.balanceOf(...)", "is_dynamic": True}
            ]
        """
        if not params_str.strip():
            return []

        # 简单的参数分割（处理嵌套括号）
        params = []
        current = ""
        depth = 0

        for char in params_str:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            elif char == ',' and depth == 0:
                params.append(current.strip())
                current = ""
                continue
            current += char

        if current.strip():
            params.append(current.strip())

        # 分析每个参数
        result = []
        for idx, param in enumerate(params):
            param_type = self._infer_param_type(param)
            is_dynamic = self._is_dynamic_param(param, param_type)

            result.append({
                "index": idx,
                "type": param_type,
                "value_expr": param,
                "is_dynamic": is_dynamic
            })

        return result

    def _is_dynamic_param(self, param_expr: str, param_type: str) -> bool:
        """
        判断参数是否为动态参数 (增强版)

        动态参数是指攻击者可能控制或调整的值，这些值通常是攻击参数的关键。

        判断策略:
        1. 包含函数调用 (如 balanceOf(...), totalSupply())
        2. 包含amount/value等关键词
        3. 是uint256类型 (数字参数通常都是关键参数)
        4. 是变量引用 (标识符)
        5. 包含算术运算 (如 amount * 2, value - 100)
        6. 数字字面量 (攻击者指定的具体数值)

        Args:
            param_expr: 参数表达式
            param_type: 推断的参数类型

        Returns:
            True如果是动态参数,否则False
        """
        param_lower = param_expr.lower()
        param_stripped = param_expr.strip()

        # 策略1: 包含函数调用 (最可靠)
        # balanceOf(...), totalSupply(), getReserves() 等
        if '(' in param_expr and ')' in param_expr:
            # 排除纯类型转换 address(this), uint256(0) 等
            # 但保留包含动态内容的转换 address(BARL)
            if not self._is_static_type_cast(param_expr):
                return True

        # 策略2: 包含金额相关关键词
        amount_keywords = ['amount', 'value', 'balance', 'reserve', 'liquidity',
                         'supply', 'debt', 'collateral', 'share', 'deposit']
        if any(kw in param_lower for kw in amount_keywords):
            return True

        # 策略3: 是uint256类型 (数字参数都可能是攻击关键)
        if param_type == 'uint256':
            return True

        # 策略4: 是变量引用 (标识符)
        # 纯变量名如 someVariable, tokenAmount
        if param_stripped.isidentifier():
            # 排除常见的非动态常量名
            non_dynamic_names = {'true', 'false'}
            if param_stripped.lower() not in non_dynamic_names:
                return True

        # 策略5: 包含算术运算
        arithmetic_ops = ['+', '-', '*', '/', '%', '<<', '>>', '&', '|', '^']
        if any(op in param_expr for op in arithmetic_ops):
            return True

        # 策略6: 数组索引访问
        if '[' in param_expr and ']' in param_expr:
            return True

        # 策略7: 成员访问 (如 token.balanceOf 已被策略1覆盖，这里处理纯属性访问)
        if '.' in param_expr and '(' not in param_expr:
            return True

        return False

    def _is_static_type_cast(self, expr: str) -> bool:
        """
        检查表达式是否为静态类型转换 (不包含动态内容)

        Args:
            expr: 表达式

        Returns:
            True如果是静态类型转换如 address(0), uint256(100), address(this)
        """
        # 匹配 address(常量), uint256(常量), bool(常量) 等
        type_cast_pattern = r'^(address|uint\d*|int\d*|bool|bytes\d*)\s*\([^()]*\)$'
        if re.match(type_cast_pattern, expr.strip()):
            # 检查括号内是否为静态内容
            inner = re.search(r'\(([^()]*)\)', expr)
            if inner:
                inner_content = inner.group(1).strip()
                # 静态内容: 数字、0x地址、this、0
                if (inner_content.isdigit() or
                    inner_content.startswith('0x') or
                    inner_content in ['this', '0']):
                    return True
        return False

    def _infer_param_type(self, param_expr: str) -> str:
        """推断参数类型"""
        # balanceOf总是返回uint256
        if 'balanceOf' in param_expr:
            return 'uint256'
        # address()强制转换
        elif param_expr.strip().startswith('address(') and not 'balanceOf' in param_expr:
            return 'address'
        # 数值字面量
        elif param_expr.endswith('e18') or (param_expr.replace('_', '').isdigit()):
            return 'uint256'
        # 数组
        elif param_expr.startswith('[') or param_expr.startswith('new '):
            return 'address[]' if 'address' in param_expr else 'uint8[]'
        # bytes类型
        elif param_expr.startswith('"') or param_expr.startswith("'"):
            return 'bytes'
        # 变量名称启发式
        elif any(name in param_expr.lower() for name in ['amount', 'value', 'count', 'percentage']):
            return 'uint256'
        else:
            return 'unknown'

    def _extract_loop_info(self) -> Optional[Dict]:
        """提取循环攻击信息"""
        # while (i < 20) { ... }
        while_pattern = r'while\s*\(\s*\w+\s*<\s*(\d+)\s*\)'
        match = re.search(while_pattern, self.script_content)

        if match:
            count = int(match.group(1))
            return {"count": count, "type": "while_loop"}

        # for (uint i = 0; i < 20; i++)
        for_pattern = r'for\s*\([^;]*;\s*\w+\s*<\s*(\d+)'
        match = re.search(for_pattern, self.script_content)

        if match:
            count = int(match.group(1))
            return {"count": count, "type": "for_loop"}

        return None


class StorageAnalyzer:
    """Storage状态分析器 - 从attack_state.json提取相关storage"""

    def __init__(self, protocol_dir: Path):
        self.protocol_dir = protocol_dir
        self.attack_state_before = self._load_json("attack_state.json")
        self.attack_state_after = self._load_json("attack_state_after.json")

    def _load_json(self, filename: str) -> Optional[Dict]:
        """加载JSON文件"""
        file_path = self.protocol_dir / filename
        if not file_path.exists():
            return None

        with open(file_path, 'r') as f:
            return json.load(f)

    def get_contract_storage(self, address: str, before=True) -> Dict:
        """
        获取指定合约的storage

        Args:
            address: 合约地址（自动处理大小写）
            before: True获取攻击前，False获取攻击后

        Returns:
            Storage字典 {slot: value}
        """
        state = self.attack_state_before if before else self.attack_state_after
        if not state:
            return {}

        addresses = state.get('addresses', {})

        # 尝试不同的地址格式
        for addr_key in addresses.keys():
            if addr_key.lower() == address.lower():
                return addresses[addr_key].get('storage', {})

        return {}

    def identify_changed_slots(self, address: str) -> List[str]:
        """识别攻击前后变化的storage槽位"""
        if not self.attack_state_before or not self.attack_state_after:
            return []

        storage_before = self.get_contract_storage(address, before=True)
        storage_after = self.get_contract_storage(address, before=False)

        changed_slots = []
        all_slots = set(storage_before.keys()) | set(storage_after.keys())

        for slot in all_slots:
            val_before = storage_before.get(slot)
            val_after = storage_after.get(slot)

            if val_before != val_after:
                changed_slots.append(slot)

        return changed_slots


class ConstraintGenerator:
    """约束生成器 - 基于启发式规则生成参数-状态约束"""

    # 常见的DeFi攻击模式
    ATTACK_PATTERNS = {
        # === 闪电贷相关攻击 ===
        'flashloan_attack': {
            'keywords': ['flashloan', 'flash'],
            'description': '闪电贷攻击',
            'constraint_template': 'amount > totalLiquidity * 0.3'
        },
        'borrow_attack': {
            'keywords': ['borrow'],
            'description': '过度借贷攻击',
            'constraint_template': 'amount > availableLiquidity * 0.8'
        },
        'repay_manipulation': {
            'keywords': ['repay', 'repayall', 'repayforall'],
            'description': '还款操纵攻击',
            'constraint_template': 'amount > borrowedAmount * 0.9'
        },

        # === 抵押/存取款攻击 ===
        'large_deposit': {
            'keywords': ['deposit', 'bond', 'stake', 'mint', 'supply'],
            'description': '大额存款攻击',
            'constraint_template': 'amount > totalSupply * 0.5'
        },
        'drain_attack': {
            'keywords': ['withdraw', 'debond', 'unstake', 'redeem', 'burn'],
            'description': '资金抽取攻击',
            'constraint_template': 'amount > balance * 0.8'
        },
        'collateral_manipulation': {
            'keywords': ['addcollateral', 'removecollateral', 'liquidate'],
            'description': '抵押品操纵',
            'constraint_template': 'amount > userCollateral * 0.9'
        },

        # === 价格操纵攻击 ===
        'swap_manipulation': {
            'keywords': ['swap', 'swapmanual', 'swapexact'],
            'description': 'Swap价格操纵',
            'constraint_template': 'amountIn > reserve * 0.3'
        },
        'price_oracle_attack': {
            'keywords': ['trade', 'exchange', 'buy', 'sell'],
            'description': '价格预言机攻击',
            'constraint_template': 'amount > poolBalance * 0.25'
        },

        # === 重入攻击 ===
        'reentrancy_attack': {
            'keywords': ['callback', 'onflashloan', 'receive', 'fallback'],
            'description': '重入攻击',
            'constraint_template': 'callDepth > maxDepth'
        },

        # === 治理攻击 ===
        'governance_attack': {
            'keywords': ['vote', 'propose', 'execute', 'delegate'],
            'description': '治理攻击',
            'constraint_template': 'votingPower > totalVotes * 0.5'
        },

        # === 桥接攻击 ===
        'bridge_attack': {
            'keywords': ['bridge', 'relay', 'lock', 'unlock'],
            'description': '跨链桥攻击',
            'constraint_template': 'amount > bridgeBalance * 0.7'
        },

        # === NFT相关攻击 ===
        'nft_manipulation': {
            'keywords': ['claim', 'harvest', 'compound'],
            'description': 'NFT/奖励操纵',
            'constraint_template': 'amount > pendingRewards * 0.8'
        }
    }

    def generate(self, attack_info: Dict, storage_info: Dict) -> List[Dict]:
        """
        生成约束规则

        Args:
            attack_info: 攻击脚本解析结果
            storage_info: Storage分析结果

        Returns:
            约束列表
        """
        constraints = []

        for call in attack_info.get('attack_calls', []):
            func_name = call['function']
            params = call['parameters']

            # 识别攻击模式
            pattern = self._identify_attack_pattern(func_name, call)

            if not pattern:
                continue

            # 生成约束
            constraint = self._generate_constraint_from_pattern(
                func_name, params, pattern, storage_info
            )

            if constraint:
                constraints.append(constraint)

        return constraints

    def _identify_attack_pattern(self, func_name: str, call_info: Dict) -> Optional[str]:
        """识别攻击模式"""
        func_lower = func_name.lower()

        for pattern_name, pattern_def in self.ATTACK_PATTERNS.items():
            keywords = pattern_def['keywords']
            if any(kw in func_lower for kw in keywords):
                return pattern_name

        return None

    def _generate_constraint_from_pattern(
        self,
        func_name: str,
        params: List[Dict],
        pattern: str,
        storage_info: Dict
    ) -> Optional[Dict]:
        """
        根据模式生成约束

        Args:
            func_name: 函数名
            params: 参数列表
            pattern: 攻击模式名称
            storage_info: Storage信息

        Returns:
            约束字典或None
        """
        # 查找数值类型的参数（通常是amount）
        amount_param = None
        for param in params:
            if param['type'] == 'uint256' and param['is_dynamic']:
                amount_param = param
                break

        if not amount_param:
            return None

        # 根据模式生成约束
        if pattern == 'large_deposit':
            return {
                "function": func_name,
                "signature": f"{func_name}(address,uint256)",
                "attack_pattern": pattern,
                "constraint": {
                    "type": "inequality",
                    "expression": "amount > totalSupply * 0.5",
                    "semantics": "Large deposit exceeding 50% of total supply",
                    "variables": {
                        "amount": {
                            "source": "function_parameter",
                            "index": amount_param['index'],
                            "type": "uint256",
                            "value_expr": amount_param['value_expr']
                        },
                        "totalSupply": {
                            "source": "storage",
                            "slot": "0x2",
                            "type": "uint256",
                            "semantic_name": "totalSupply"
                        }
                    },
                    "danger_condition": "amount > totalSupply * 0.5",
                    "safe_condition": "amount <= totalSupply * 0.1"
                }
            }

        elif pattern == 'flashloan_attack':
            return {
                "function": func_name,
                "signature": f"{func_name}(address,address,address,uint256,bytes)",
                "attack_pattern": pattern,
                "constraint": {
                    "type": "inequality",
                    "expression": "amount > totalLiquidity * 0.3",
                    "semantics": "Large flashloan exceeding 30% of pool liquidity",
                    "variables": {
                        "amount": {
                            "source": "function_parameter",
                            "index": amount_param['index'],
                            "type": "uint256",
                            "value_expr": amount_param['value_expr']
                        },
                        "totalLiquidity": {
                            "source": "storage",
                            "slot": "0x3",
                            "type": "uint256",
                            "semantic_name": "totalLiquidity"
                        }
                    },
                    "danger_condition": "amount > totalLiquidity * 0.3",
                    "safe_condition": "amount <= totalLiquidity * 0.05"
                }
            }

        elif pattern == 'borrow_attack':
            return {
                "function": func_name,
                "signature": f"{func_name}(address,uint256)",
                "attack_pattern": pattern,
                "constraint": {
                    "type": "inequality",
                    "expression": "amount > availableLiquidity * 0.8",
                    "semantics": "Excessive borrowing depleting pool liquidity",
                    "variables": {
                        "amount": {
                            "source": "function_parameter",
                            "index": amount_param['index'],
                            "type": "uint256",
                            "value_expr": amount_param['value_expr']
                        },
                        "availableLiquidity": {
                            "source": "storage",
                            "slot": "0x4",
                            "type": "uint256",
                            "semantic_name": "availableLiquidity"
                        }
                    },
                    "danger_condition": "amount > availableLiquidity * 0.8",
                    "safe_condition": "amount <= availableLiquidity * 0.3"
                }
            }

        elif pattern == 'repay_manipulation':
            return {
                "function": func_name,
                "signature": f"{func_name}(address,bool,uint256)",
                "attack_pattern": pattern,
                "constraint": {
                    "type": "inequality",
                    "expression": "amount > borrowedAmount * 0.9",
                    "semantics": "Large repayment potentially manipulating debt tracking",
                    "variables": {
                        "amount": {
                            "source": "function_parameter",
                            "index": amount_param['index'],
                            "type": "uint256",
                            "value_expr": amount_param['value_expr']
                        },
                        "borrowedAmount": {
                            "source": "storage",
                            "slot": "dynamic",
                            "type": "uint256",
                            "semantic_name": "userBorrowPart"
                        }
                    },
                    "danger_condition": "amount > borrowedAmount * 0.9",
                    "safe_condition": "amount <= borrowedAmount * 0.5"
                }
            }

        elif pattern == 'swap_manipulation':
            return {
                "function": func_name,
                "signature": f"{func_name}(uint256)",
                "attack_pattern": pattern,
                "constraint": {
                    "type": "inequality",
                    "expression": "amountIn > reserve * 0.3",
                    "semantics": "Large swap causing significant price slippage",
                    "variables": {
                        "amountIn": {
                            "source": "function_parameter",
                            "index": amount_param['index'],
                            "type": "uint256",
                            "value_expr": amount_param['value_expr']
                        },
                        "reserve": {
                            "source": "storage",
                            "slot": "0x5",
                            "type": "uint256",
                            "semantic_name": "reserve"
                        }
                    },
                    "danger_condition": "amountIn > reserve * 0.3",
                    "safe_condition": "amountIn <= reserve * 0.05"
                }
            }

        elif pattern == 'price_oracle_attack':
            return {
                "function": func_name,
                "signature": f"{func_name}(uint256)",
                "attack_pattern": pattern,
                "constraint": {
                    "type": "inequality",
                    "expression": "amount > poolBalance * 0.25",
                    "semantics": "Trade volume manipulating oracle price",
                    "variables": {
                        "amount": {
                            "source": "function_parameter",
                            "index": amount_param['index'],
                            "type": "uint256"
                        },
                        "poolBalance": {
                            "source": "storage",
                            "slot": "0x6",
                            "type": "uint256",
                            "semantic_name": "poolBalance"
                        }
                    },
                    "danger_condition": "amount > poolBalance * 0.25",
                    "safe_condition": "amount <= poolBalance * 0.05"
                }
            }

        elif pattern == 'collateral_manipulation':
            return {
                "function": func_name,
                "signature": f"{func_name}(address,bool,uint256)",
                "attack_pattern": pattern,
                "constraint": {
                    "type": "inequality",
                    "expression": "amount > userCollateral * 0.9",
                    "semantics": "Large collateral change affecting liquidation threshold",
                    "variables": {
                        "amount": {
                            "source": "function_parameter",
                            "index": amount_param['index'],
                            "type": "uint256",
                            "value_expr": amount_param['value_expr']
                        },
                        "userCollateral": {
                            "source": "storage",
                            "slot": "dynamic",
                            "type": "uint256",
                            "semantic_name": "userCollateralShare"
                        }
                    },
                    "danger_condition": "amount > userCollateral * 0.9",
                    "safe_condition": "amount <= userCollateral * 0.3"
                }
            }

        elif pattern == 'drain_attack':
            return {
                "function": func_name,
                "signature": f"{func_name}(uint256,address[],uint8[])",
                "attack_pattern": pattern,
                "constraint": {
                    "type": "inequality",
                    "expression": "amount > userBalance * 0.9",
                    "semantics": "Draining large portion of user balance",
                    "variables": {
                        "amount": {
                            "source": "function_parameter",
                            "index": amount_param['index'],
                            "type": "uint256",
                            "value_expr": amount_param['value_expr']
                        },
                        "userBalance": {
                            "source": "storage",
                            "slot": "dynamic",
                            "type": "uint256",
                            "semantic_name": "balanceOf(attacker)"
                        }
                    },
                    "danger_condition": "amount > userBalance * 0.9",
                    "safe_condition": "amount <= userBalance * 0.5"
                }
            }

        elif pattern == 'nft_manipulation':
            return {
                "function": func_name,
                "signature": f"{func_name}()",
                "attack_pattern": pattern,
                "constraint": {
                    "type": "inequality",
                    "expression": "claimAmount > pendingRewards * 0.8",
                    "semantics": "Claiming excessive rewards through manipulation",
                    "variables": {
                        "claimAmount": {
                            "source": "return_value",
                            "type": "uint256",
                            "semantic_name": "claimed_amount"
                        },
                        "pendingRewards": {
                            "source": "storage",
                            "slot": "dynamic",
                            "type": "uint256",
                            "semantic_name": "userPendingRewards"
                        }
                    },
                    "danger_condition": "claimAmount > pendingRewards * 0.8",
                    "safe_condition": "claimAmount <= pendingRewards * 0.5"
                }
            }

        # 默认返回None表示不支持此模式
        return None


class ConstraintExtractor:
    """主提取器 - 协调各个组件"""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.extracted_dir = repo_root / "extracted_contracts"
        self.scripts_dir = repo_root / "src" / "test"

    def extract_single(self, protocol_name: str, year_month: str) -> Optional[Dict]:
        """
        提取单个协议的约束

        Args:
            protocol_name: 协议名称，如 "BarleyFinance_exp"
            year_month: 年月，如 "2024-01"

        Returns:
            完整的constraint_rules字典，失败时返回None
        """
        logger.info(f"开始提取约束: {protocol_name}")

        # 1. 定位文件路径
        protocol_dir = self.extracted_dir / year_month / protocol_name
        script_path = self.scripts_dir / year_month / f"{protocol_name}.sol"

        if not script_path.exists():
            logger.warning(f"攻击脚本不存在: {script_path}")
            return None

        if not protocol_dir.exists():
            logger.warning(f"协议目录不存在: {protocol_dir}")
            return None

        # 2. 解析攻击脚本
        parser = AttackScriptParser(script_path)
        attack_info = parser.parse()

        vulnerable_contract = attack_info.get('vulnerable_contract', {})
        logger.info(f"  被攻击合约: {vulnerable_contract.get('name')} ({vulnerable_contract.get('address')})")
        logger.info(f"  识别到 {len(attack_info.get('attack_calls', []))} 个函数调用")

        # 3. 分析Storage
        storage_analyzer = StorageAnalyzer(protocol_dir)
        vuln_address = vulnerable_contract.get('address')

        storage_info = {}
        if vuln_address:
            storage_before = storage_analyzer.get_contract_storage(vuln_address, before=True)
            changed_slots = storage_analyzer.identify_changed_slots(vuln_address)

            storage_info = {
                "storage_before": storage_before,
                "changed_slots": changed_slots
            }
            logger.info(f"  Storage槽位变化: {len(changed_slots)} 个")

        # 4. 生成约束
        constraint_gen = ConstraintGenerator()
        constraints = constraint_gen.generate(attack_info, storage_info)

        logger.success(f"  生成约束: {len(constraints)} 个")

        # 5. 构建最终结果
        loop_info = attack_info.get('loop_info') or {}
        result = {
            "protocol": protocol_name,
            "year_month": year_month,
            "vulnerable_contract": vulnerable_contract,
            "constraints": constraints,
            "storage_analysis": {
                "changed_slots": storage_info.get('changed_slots', []),
                "total_slots": len(storage_info.get('storage_before', {}))
            },
            "attack_metadata": {
                "loop_count": loop_info.get('count', 1),
                "total_calls": len(attack_info.get('attack_calls', []))
            },
            "metadata": {
                "extraction_version": "1.0.0",
                "generated_by": "extract_param_state_constraints.py"
            }
        }

        return result

    def save_result(self, result: Dict, protocol_name: str, year_month: str):
        """保存结果到constraint_rules.json"""
        if not result:
            return

        output_path = self.extracted_dir / year_month / protocol_name / "constraint_rules.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        logger.success(f"约束规则已保存: {output_path}")

    def batch_extract(self, year_month_filter: str = None) -> Dict[str, Dict]:
        """
        批量提取多个协议

        Args:
            year_month_filter: 可选的年月过滤，如 "2024-01"

        Returns:
            {protocol_name: constraint_result}
        """
        results = {}

        # 扫描extracted_contracts目录
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

                try:
                    result = self.extract_single(protocol_name, year_month)
                    if result is not None:  # ✅ 修复：明确检查None
                        self.save_result(result, protocol_name, year_month)
                        results[protocol_name] = result
                except Exception as e:
                    logger.error(f"处理 {protocol_name} 时出错: {e}")

        return results


def main():
    parser = argparse.ArgumentParser(
        description="从攻击PoC中提取参数-状态约束关系",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 单个协议
  python extract_param_state_constraints.py --protocol BarleyFinance_exp --year-month 2024-01

  # 批量处理2024-01的所有协议
  python extract_param_state_constraints.py --batch --filter 2024-01

  # 批量处理所有协议
  python extract_param_state_constraints.py --batch
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

    parser.add_argument(
        '--output',
        help='自定义输出路径（默认: extracted_contracts/{year-month}/{protocol}/constraint_rules.json）'
    )

    args = parser.parse_args()

    # 确定repo根目录
    script_dir = Path(__file__).parent
    repo_root = script_dir

    extractor = ConstraintExtractor(repo_root)

    if args.batch:
        # 批量模式
        logger.info("=== 批量提取模式 ===")
        results = extractor.batch_extract(year_month_filter=args.filter)
        logger.success(f"\n总计处理: {len(results)} 个协议")

    elif args.protocol and args.year_month:
        # 单个协议模式
        logger.info("=== 单协议提取模式 ===")
        result = extractor.extract_single(args.protocol, args.year_month)

        if result:
            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                logger.success(f"结果已保存到: {output_path}")
            else:
                extractor.save_result(result, args.protocol, args.year_month)
        else:
            logger.error("提取失败")
            sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
