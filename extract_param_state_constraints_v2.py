#!/usr/bin/env python3
"""
参数-状态约束提取器 V2 (Parameter-State Constraint Extractor V2)

改进版本 - 基于攻击前后状态差异分析生成约束

核心改进:
1. 分析攻击前后状态差异，找到真正受影响的slot
2. 关联函数参数与状态slot变化
3. 从实际攻击行为推断阈值系数
4. 动态识别slot语义

作者: FirewallOnchain Team
版本: 2.0.0
日期: 2025-01-21
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal, getcontext
from collections import defaultdict

# 设置高精度
getcontext().prec = 78

# 配置日志
class Logger:
    """简单的彩色日志器"""
    COLORS = {
        'info': '\033[0;34m',
        'success': '\033[0;32m',
        'warning': '\033[1;33m',
        'error': '\033[0;31m',
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


# =============================================================================
# 工具函数
# =============================================================================

def to_int(val) -> int:
    """将各种格式的值转为整数"""
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        if val.startswith('0x'):
            return int(val, 16)
        try:
            return int(val, 16)
        except ValueError:
            return int(val)
    return 0


def to_decimal(val) -> Decimal:
    """转换为Decimal以保持精度"""
    return Decimal(str(to_int(val)))


# =============================================================================
# 状态差异分析器
# =============================================================================

class StateDiffAnalyzer:
    """分析攻击前后的状态差异"""

    def __init__(self, protocol_dir: Path):
        self.protocol_dir = protocol_dir
        self.state_before = self._load_json("attack_state.json")
        self.state_after = self._load_json("attack_state_after.json")
        self.addresses_info = self._load_json("addresses.json")

    def _load_json(self, filename: str) -> Optional[Dict]:
        file_path = self.protocol_dir / filename
        if not file_path.exists():
            return None
        with open(file_path, 'r') as f:
            return json.load(f)

    def get_contract_storage(self, address: str, before: bool = True) -> Dict:
        """获取指定合约的storage"""
        state = self.state_before if before else self.state_after
        if not state:
            return {}

        addresses = state.get('addresses', {})
        for addr_key in addresses.keys():
            if addr_key.lower() == address.lower():
                return addresses[addr_key].get('storage', {})
        return {}

    def analyze_slot_changes(self, address: str) -> List[Dict]:
        """
        分析合约的slot变化

        Returns:
            [
                {
                    'slot': '2',
                    'before': 8611951186321848770844714,
                    'after': 15449840428261396694895415,
                    'change': 6837889241939547924050701,
                    'change_pct': 79.40,
                    'change_direction': 'increase'
                }
            ]
        """
        storage_before = self.get_contract_storage(address, before=True)
        storage_after = self.get_contract_storage(address, before=False)

        if not storage_before or not storage_after:
            return []

        all_slots = set(storage_before.keys()) | set(storage_after.keys())
        changes = []

        for slot in all_slots:
            val_before = storage_before.get(slot, '0x0')
            val_after = storage_after.get(slot, '0x0')

            if val_before != val_after:
                before_int = to_int(val_before)
                after_int = to_int(val_after)
                change = after_int - before_int

                # 计算变化率和新建标记
                is_new_slot = (before_int == 0 and after_int != 0)
                is_cleared_slot = (before_int != 0 and after_int == 0)

                if before_int != 0:
                    change_pct = abs(change) / before_int * 100
                elif after_int != 0:
                    # 从0变化，使用特殊处理：用after值作为"相对重要性"
                    change_pct = 100.0  # 标记为100%变化（新建slot）
                else:
                    change_pct = 0

                changes.append({
                    'slot': slot,
                    'before': before_int,
                    'after': after_int,
                    'change': change,
                    'change_abs': abs(change),
                    'change_pct': change_pct,
                    'change_direction': 'increase' if change > 0 else 'decrease',
                    'is_new_slot': is_new_slot,
                    'is_cleared_slot': is_cleared_slot
                })

        # 按变化绝对值排序
        return sorted(changes, key=lambda x: x['change_abs'], reverse=True)

    def get_token_balance(self, token_name: str, holder_name: str) -> Optional[int]:
        """
        从addresses.json获取token余额

        Args:
            token_name: token名称 (如 'BARL', 'wBARL')
            holder_name: 持有者名称 (如 'wBARL', 'Attacker')
        """
        if not self.addresses_info:
            return None

        # 查找token和holder的地址
        token_addr = None
        holder_addr = None

        for addr, info in self.addresses_info.items():
            name = info.get('name', '')
            if name == token_name or token_name in name:
                token_addr = addr
            if name == holder_name or holder_name in name:
                holder_addr = addr

        if not token_addr or not holder_addr:
            return None

        # 从攻击前状态获取余额
        if self.state_before:
            addresses = self.state_before.get('addresses', {})
            for addr_key in addresses.keys():
                if addr_key.lower() == token_addr.lower():
                    storage = addresses[addr_key].get('storage', {})
                    # 这里需要计算balanceOf的slot
                    # ERC20的balanceOf通常在keccak256(holder || slot)
                    # 简化处理：返回None，让调用者使用其他方法
                    break

        return None

    def _parse_contract_storage_layout(self, contract_dir: Path) -> Dict[int, str]:
        """
        从合约源码解析storage布局

        Returns:
            {slot_index: variable_name}
        """
        storage_layout = {}

        # 查找主合约源码
        sol_files = list(contract_dir.glob("contracts/*.sol"))
        if not sol_files:
            sol_files = list(contract_dir.glob("*.sol"))

        for sol_file in sol_files:
            try:
                content = sol_file.read_text()

                # 检查是否继承ERC20
                if 'ERC20' in content or 'IERC20' in content:
                    # ERC20标准布局
                    storage_layout[0] = "_balances"
                    storage_layout[1] = "_allowances"
                    storage_layout[2] = "_totalSupply"
                    storage_layout[3] = "_name"
                    storage_layout[4] = "_symbol"

                # 提取状态变量声明
                # 匹配: uint256 public variableName;
                # 匹配: mapping(address => uint256) public balances;
                state_var_patterns = [
                    r'^\s*(uint\d*|int\d*|address|bool|bytes\d*|string)\s+(?:public\s+|private\s+|internal\s+)?(\w+)\s*[;=]',
                    r'^\s*mapping\s*\([^)]+\)\s+(?:public\s+|private\s+|internal\s+)?(\w+)\s*;',
                    r'^\s*(IndexType|IndexAssetInfo\[\])\s+(?:public\s+|private\s+|internal\s+)?(?:override\s+)?(\w+)\s*;',
                ]

                current_slot = 5 if storage_layout else 0  # 如果有ERC20，从slot 5开始

                for line in content.split('\n'):
                    # 跳过注释和空行
                    if line.strip().startswith('//') or not line.strip():
                        continue
                    # 跳过immutable和constant
                    if 'immutable' in line or 'constant' in line:
                        continue

                    for pattern in state_var_patterns:
                        match = re.search(pattern, line)
                        if match:
                            var_name = match.group(2) if len(match.groups()) > 1 else match.group(1)
                            if var_name and not var_name.startswith('_') or var_name in ['_swapping', '_swapOn']:
                                storage_layout[current_slot] = var_name
                                current_slot += 1
                            break

            except Exception as e:
                logger.warning(f"解析合约源码失败: {sol_file}: {e}")

        return storage_layout

    def infer_slot_semantic(self, slot: str, change_info: Dict, contract_name: str) -> str:
        """
        推断slot的语义 - 优先使用源码分析，回退到启发式方法

        基于以下线索:
        1. 合约源码中的状态变量声明
        2. slot索引
        3. 变化模式 (增加/减少)
        4. 变化幅度
        """
        slot_int = int(slot) if slot.isdigit() else int(slot, 16) if slot.startswith('0x') else -1

        # 1. 尝试从源码获取语义
        if hasattr(self, '_storage_layout_cache'):
            if slot_int in self._storage_layout_cache:
                return self._storage_layout_cache[slot_int]
        else:
            # 初始化缓存并尝试解析
            self._storage_layout_cache = {}
            if self.protocol_dir:
                # 查找被攻击合约的源码目录
                for subdir in self.protocol_dir.iterdir():
                    if subdir.is_dir() and contract_name.lower() in subdir.name.lower():
                        self._storage_layout_cache = self._parse_contract_storage_layout(subdir)
                        break

            if slot_int in self._storage_layout_cache:
                return self._storage_layout_cache[slot_int]

        # 2. 基于slot值特征推断
        # 长slot值通常是mapping的key (keccak256结果)
        if len(str(slot)) > 20:
            # 尝试从变化模式推断mapping类型
            change_pct = change_info.get('change_pct', 0)
            direction = change_info.get('change_direction', '')
            is_new = change_info.get('is_new_slot', False)

            if is_new:
                return "new_mapping_entry"
            elif direction == 'increase':
                return "balance_mapping_increased"
            elif direction == 'decrease':
                return "balance_mapping_decreased"
            else:
                return "mapping_entry"

        # 3. 基于小slot索引的启发式推断（仅作为后备）
        # 注意：这些是常见模式，但不总是准确
        if slot_int == 2:
            return "likely_totalSupply"
        elif slot_int == 0:
            return "likely_balances_mapping"
        elif slot_int == 1:
            return "likely_allowances_mapping"

        # 4. 基于变化模式推断
        change_pct = change_info.get('change_pct', 0)
        direction = change_info.get('change_direction', '')

        if change_pct > 50:
            if direction == 'increase':
                return "accumulated_value"
            else:
                return "drained_balance"

        return f"slot_{slot_int}"


# =============================================================================
# 参数-状态关联分析器
# =============================================================================

class ParamStateCorrelator:
    """关联函数参数与状态变化"""

    def __init__(self, state_analyzer: StateDiffAnalyzer):
        self.state_analyzer = state_analyzer

    def correlate(self, param_value: int, slot_changes: List[Dict]) -> List[Dict]:
        """
        查找参数值与slot变化的关联

        关联类型:
        1. 直接相等: param ≈ slot_change
        2. 比例关系: param × ratio ≈ slot_change
        3. 累积关系: param × iterations ≈ slot_change

        Returns:
            [
                {
                    'slot': '2',
                    'correlation_type': 'direct',
                    'confidence': 0.95,
                    'ratio': 1.0
                }
            ]
        """
        if param_value == 0:
            return []

        correlations = []

        for change in slot_changes:
            change_abs = change['change_abs']

            if change_abs == 0:
                continue

            # 计算比例
            ratio = change_abs / param_value

            # 直接相等 (误差<1%)
            if 0.99 < ratio < 1.01:
                correlations.append({
                    'slot': change['slot'],
                    'correlation_type': 'direct',
                    'confidence': 0.95,
                    'ratio': ratio,
                    'slot_change': change
                })

            # 2倍关系 (常见于存款/取款)
            elif 1.98 < ratio < 2.02:
                correlations.append({
                    'slot': change['slot'],
                    'correlation_type': 'double',
                    'confidence': 0.85,
                    'ratio': ratio,
                    'slot_change': change
                })

            # 整数倍关系 (循环攻击)
            elif ratio > 2 and abs(ratio - round(ratio)) < 0.1:
                correlations.append({
                    'slot': change['slot'],
                    'correlation_type': 'multiple',
                    'confidence': 0.75,
                    'ratio': ratio,
                    'iterations': round(ratio),
                    'slot_change': change
                })

            # 分数关系 (部分提取)
            elif 0.1 < ratio < 0.99:
                correlations.append({
                    'slot': change['slot'],
                    'correlation_type': 'partial',
                    'confidence': 0.70,
                    'ratio': ratio,
                    'slot_change': change
                })

            # 极大比例 (参数远小于变化量，可能是杠杆/放大效应)
            elif ratio > 10:
                correlations.append({
                    'slot': change['slot'],
                    'correlation_type': 'amplified',
                    'confidence': 0.60,
                    'ratio': ratio,
                    'amplification_factor': ratio,
                    'slot_change': change
                })

        return sorted(correlations, key=lambda x: x['confidence'], reverse=True)


# =============================================================================
# 动态阈值推断器
# =============================================================================

class ThresholdInferrer:
    """从实际攻击行为推断安全阈值"""

    # 攻击强度到安全阈值的映射
    INTENSITY_TO_THRESHOLD = {
        # 攻击强度 -> 建议的安全阈值
        (0.9, 1.0): 0.3,   # 攻击用了90-100%, 阈值设30%
        (0.7, 0.9): 0.4,   # 攻击用了70-90%, 阈值设40%
        (0.5, 0.7): 0.5,   # 攻击用了50-70%, 阈值设50%
        (0.3, 0.5): 0.6,   # 攻击用了30-50%, 阈值设60%
        (0.0, 0.3): 0.7,   # 攻击用了<30%, 阈值设70%
    }

    def infer_threshold(self, attack_param: int, state_value: int, attack_pattern: str) -> Dict:
        """
        推断安全阈值

        Args:
            attack_param: 攻击时使用的参数值
            state_value: 攻击前的状态值
            attack_pattern: 攻击模式

        Returns:
            {
                'coefficient': 0.3,
                'threshold': 计算后的阈值,
                'attack_intensity': 攻击强度,
                'reasoning': '...'
            }
        """
        if state_value == 0:
            return {
                'coefficient': 0.5,
                'threshold': attack_param // 2,
                'attack_intensity': 1.0,
                'reasoning': '状态值为0，使用默认系数0.5'
            }

        # 计算攻击强度
        attack_intensity = attack_param / state_value

        # 根据攻击强度确定系数
        coefficient = 0.5  # 默认
        for (low, high), coef in self.INTENSITY_TO_THRESHOLD.items():
            if low <= attack_intensity < high:
                coefficient = coef
                break

        # 根据攻击模式调整
        if attack_pattern in ['flashloan_attack', 'drain_attack']:
            # 闪电贷和抽取攻击需要更严格的阈值
            coefficient = min(coefficient, 0.3)
        elif attack_pattern in ['large_deposit', 'borrow_attack']:
            # 存款和借贷可以稍微宽松
            coefficient = min(coefficient, 0.5)

        threshold = int(state_value * Decimal(str(coefficient)))

        return {
            'coefficient': coefficient,
            'threshold': threshold,
            'attack_intensity': round(attack_intensity, 4),
            'reasoning': f'攻击使用了状态值的{attack_intensity*100:.1f}%，设置阈值为{coefficient*100:.0f}%'
        }


# =============================================================================
# 攻击脚本解析器 (复用v1的基础逻辑)
# =============================================================================

class AttackScriptParser:
    """攻击脚本解析器"""

    def __init__(self, script_path: Path):
        self.script_path = script_path
        self.script_content = script_path.read_text()

    def parse(self) -> Dict:
        result = {
            "vulnerable_contract": self._extract_vulnerable_contract(),
            "attack_calls": self._extract_attack_calls(),
            "loop_info": self._extract_loop_info()
        }
        return result

    def _extract_vulnerable_contract(self) -> Dict:
        """从注释中提取被攻击合约信息"""
        patterns = [
            r'//\s*Vuln(?:erable)?\s+Contract\s*:\s*https?://[^/]+/address/(0x[a-fA-F0-9]{40})',
            r'-\s*Vuln(?:erable)?\s+Contract\s*:\s*https?://[^/]+/address/(0x[a-fA-F0-9]{40})',
            r'//\s*Vuln(?:erable)?\s+Contract\s*:\s*(0x[a-fA-F0-9]{40})',
            r'//\s*Victim\s+Contract\s*:\s*https?://[^/]+/address/(0x[a-fA-F0-9]{40})',
            r'//\s*Vuln(?:erable)?\s*:\s*https?://[^/]+/address/(0x[a-fA-F0-9]{40})',
        ]

        for pattern in patterns:
            match = re.search(pattern, self.script_content, re.IGNORECASE)
            if match:
                address = match.group(1)
                name = self._infer_contract_name(address)
                return {"address": address, "name": name}

        return {"address": None, "name": None}

    def _infer_contract_name(self, address: str) -> str:
        """从地址推断合约名称"""
        # 将地址转换为不区分大小写的正则模式
        # 例如 0x37e49bf -> (?i)0x37e49bf 或逐字符 [3][7][eE][4]...
        addr_pattern = ''.join(
            f'[{c.lower()}{c.upper()}]' if c.isalpha() else c
            for c in address
        )

        # 模式1: 变量赋值 wBARL = IwBARL(0x...)
        pattern1 = rf'(\w+)\s*=\s*I\w+\s*\(\s*(?:payable\s*\()?\s*{addr_pattern}\s*\)?'
        match = re.search(pattern1, self.script_content)
        if match:
            return match.group(1)  # 保持原始大小写

        # 模式2: 常量定义 address constant name = 0x...
        pattern2 = rf'address\s+(?:constant|immutable)?\s*(\w+)\s*=\s*{addr_pattern}'
        match = re.search(pattern2, self.script_content)
        if match:
            return match.group(1)

        # 模式3: 接口声明 IContract name = IContract(0x...)
        pattern3 = rf'I(\w+)\s+(?:public\s+)?(\w+)\s*=\s*I\w+\s*\(\s*(?:payable\s*\()?\s*{addr_pattern}'
        match = re.search(pattern3, self.script_content)
        if match:
            return match.group(2)  # 返回变量名而不是接口名

        return "Unknown"

    def _extract_attack_calls(self) -> List[Dict]:
        """提取对被攻击合约的函数调用"""
        calls = []
        vuln_contract = self._extract_vulnerable_contract()
        contract_name = vuln_contract.get("name", "")

        if not contract_name or contract_name == "Unknown":
            return calls

        pattern = rf'{contract_name}\.(\w+)\s*\('

        for line_no, line in enumerate(self.script_content.split('\n'), 1):
            if line.strip().startswith('//') or 'interface' in line:
                continue

            if contract_name not in line:
                continue

            for match in re.finditer(pattern, line):
                func_name = match.group(1)

                # 跳过ERC20标准函数
                if func_name in ['balanceOf', 'allowance', 'approve', 'transfer', 'transferFrom', 'totalSupply']:
                    continue

                # 提取参数
                start_pos = match.end()
                params_str = self._extract_balanced_parens(line[start_pos:])
                params = self._parse_parameters(func_name, params_str)

                calls.append({
                    "function": func_name,
                    "signature": f"{func_name}({','.join([p['type'] for p in params])})",
                    "parameters": params,
                    "line_number": line_no
                })

        return calls

    def _extract_balanced_parens(self, text: str) -> str:
        """提取平衡括号内容"""
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
        """解析函数参数"""
        if not params_str.strip():
            return []

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

        result = []
        for idx, param in enumerate(params):
            param_type = self._infer_param_type(param)
            is_dynamic = param_type == 'uint256'  # 所有uint256都视为动态

            result.append({
                "index": idx,
                "type": param_type,
                "value_expr": param,
                "is_dynamic": is_dynamic
            })

        return result

    def _infer_param_type(self, param_expr: str) -> str:
        """推断参数类型"""
        if 'balanceOf' in param_expr:
            return 'uint256'
        elif param_expr.strip().startswith('address('):
            return 'address'
        elif param_expr.endswith('e18') or param_expr.replace('_', '').isdigit():
            return 'uint256'
        elif param_expr.startswith('[') or param_expr.startswith('new '):
            return 'address[]' if 'address' in param_expr else 'uint8[]'
        elif param_expr.startswith('"') or param_expr.startswith("'"):
            return 'bytes'
        elif any(name in param_expr.lower() for name in ['amount', 'value', 'count']):
            return 'uint256'
        else:
            return 'uint256'  # 默认为uint256

    def _extract_loop_info(self) -> Optional[Dict]:
        """提取循环信息"""
        patterns = [
            (r'while\s*\(\s*\w+\s*<\s*(\d+)\s*\)', 'while'),
            (r'for\s*\([^;]*;\s*\w+\s*<\s*(\d+)', 'for'),
        ]

        for pattern, loop_type in patterns:
            match = re.search(pattern, self.script_content)
            if match:
                return {"count": int(match.group(1)), "type": loop_type}

        return None


# =============================================================================
# 改进的约束生成器
# =============================================================================

class ConstraintGeneratorV2:
    """改进的约束生成器 - 基于状态差异分析"""

    def __init__(self, state_analyzer: StateDiffAnalyzer):
        self.state_analyzer = state_analyzer
        self.correlator = ParamStateCorrelator(state_analyzer)
        self.threshold_inferrer = ThresholdInferrer()
        self._behavior_analysis_cache = None

    def _analyze_attack_behavior(self, slot_changes: List[Dict], loop_info: Optional[Dict]) -> Dict:
        """
        基于状态变化分析攻击行为特征

        Returns:
            {
                'behavior_type': 'drain'|'inflate'|'loop'|'manipulation',
                'characteristics': {...},
                'confidence': 0.0-1.0
            }
        """
        if not slot_changes:
            return {'behavior_type': 'unknown', 'characteristics': {}, 'confidence': 0.0}

        # 统计特征
        new_slots = sum(1 for c in slot_changes if c.get('is_new_slot', False))
        increased_slots = sum(1 for c in slot_changes if c.get('change_direction') == 'increase')
        decreased_slots = sum(1 for c in slot_changes if c.get('change_direction') == 'decrease')
        total_slots = len(slot_changes)

        # 找到totalSupply相关的slot变化
        supply_change = None
        for c in slot_changes:
            slot_str = str(c.get('slot', ''))
            if slot_str == '2' or 'supply' in str(c).lower():
                supply_change = c
                break

        # 计算平均变化幅度
        avg_change_pct = sum(c.get('change_pct', 0) for c in slot_changes if c.get('change_pct', 0) < 10000) / max(total_slots, 1)

        loop_count = loop_info.get('count', 1) if loop_info else 1

        characteristics = {
            'new_slots_ratio': new_slots / max(total_slots, 1),
            'increase_ratio': increased_slots / max(total_slots, 1),
            'decrease_ratio': decreased_slots / max(total_slots, 1),
            'avg_change_pct': avg_change_pct,
            'loop_count': loop_count,
            'supply_direction': supply_change.get('change_direction') if supply_change else None,
            'supply_change_pct': supply_change.get('change_pct', 0) if supply_change else 0
        }

        # 基于特征推断攻击行为类型
        behavior_type, confidence = self._classify_behavior(characteristics)

        return {
            'behavior_type': behavior_type,
            'characteristics': characteristics,
            'confidence': confidence
        }

    def _classify_behavior(self, chars: Dict) -> Tuple[str, float]:
        """基于特征分类攻击行为"""

        # 循环攻击特征: 大量新建slot + 高循环次数
        if chars['new_slots_ratio'] > 0.5 and chars['loop_count'] > 5:
            return ('loop_attack', 0.9)

        # 资金抽取特征: 减少为主 + supply减少
        if chars['decrease_ratio'] > 0.6 and chars['supply_direction'] == 'decrease':
            return ('drain_attack', 0.85)

        # 通胀攻击特征: 增加为主 + supply大幅增加
        if chars['increase_ratio'] > 0.6 and chars['supply_change_pct'] > 50:
            return ('inflate_attack', 0.85)

        # 闪电贷特征: supply先增后减或大幅波动
        if chars['supply_change_pct'] > 30 and chars['loop_count'] >= 1:
            return ('flashloan_attack', 0.75)

        # 价格操纵特征: 少量slot大幅变化
        if chars['avg_change_pct'] > 100 and chars['new_slots_ratio'] < 0.3:
            return ('price_manipulation', 0.7)

        # 大额操作: 单次大变化
        if chars['avg_change_pct'] > 50:
            if chars['increase_ratio'] > chars['decrease_ratio']:
                return ('large_deposit', 0.65)
            else:
                return ('large_withdraw', 0.65)

        return ('unknown', 0.5)

    def _identify_attack_pattern(self, func_name: str, slot_changes: List[Dict] = None, loop_info: Dict = None) -> str:
        """
        识别攻击模式 - 优先使用行为分析，回退到函数名

        改进：基于实际状态变化而非函数名关键词
        """
        # 1. 首先尝试基于行为分析
        if slot_changes:
            if self._behavior_analysis_cache is None:
                self._behavior_analysis_cache = self._analyze_attack_behavior(slot_changes, loop_info)

            behavior = self._behavior_analysis_cache
            if behavior['confidence'] >= 0.7:
                return behavior['behavior_type']

        # 2. 回退到函数名关键词（降低优先级）
        func_lower = func_name.lower()

        # 简化的关键词映射，仅作为后备
        keyword_patterns = {
            'flashloan_attack': ['flash'],
            'drain_attack': ['withdraw', 'redeem', 'burn', 'debond'],
            'large_deposit': ['deposit', 'mint', 'bond', 'stake'],
            'borrow_attack': ['borrow'],
            'swap_manipulation': ['swap'],
        }

        for pattern, keywords in keyword_patterns.items():
            if any(kw in func_lower for kw in keywords):
                return pattern

        # 3. 如果行为分析有结果但置信度低，仍然使用
        if self._behavior_analysis_cache and self._behavior_analysis_cache['behavior_type'] != 'unknown':
            return self._behavior_analysis_cache['behavior_type']

        return 'unknown'

    def generate(self, attack_info: Dict, vuln_address: str) -> List[Dict]:
        """
        生成约束规则

        核心改进:
        1. 分析状态差异找到真正变化的slot
        2. 关联参数与slot变化
        3. 推断合理的阈值
        """
        constraints = []

        # 1. 获取slot变化
        slot_changes = self.state_analyzer.analyze_slot_changes(vuln_address)

        if not slot_changes:
            logger.warning("未检测到状态变化，使用启发式约束生成")
            return self._generate_heuristic_constraints(attack_info)

        logger.info(f"检测到 {len(slot_changes)} 个slot变化")

        # 获取循环信息用于行为分析
        loop_info = attack_info.get('loop_info')

        # 重置行为分析缓存
        self._behavior_analysis_cache = None

        # 2. 为每个攻击调用生成约束
        for call in attack_info.get('attack_calls', []):
            func_name = call['function']
            params = call['parameters']

            # 识别攻击模式 - 使用行为分析
            pattern = self._identify_attack_pattern(func_name, slot_changes, loop_info)
            if not pattern or pattern == 'unknown':
                continue

            # 找到动态参数
            dynamic_params = [p for p in params if p['is_dynamic'] and p['type'] == 'uint256']

            for param in dynamic_params:
                # 尝试解析参数值
                param_value = self._estimate_param_value(param['value_expr'], vuln_address)

                if param_value is None or param_value == 0:
                    continue

                # 关联参数与slot变化
                correlations = self.correlator.correlate(param_value, slot_changes)

                if correlations:
                    # 使用最佳关联
                    best_corr = correlations[0]
                    slot_change = best_corr['slot_change']

                    # 推断阈值 - 对于新建slot使用after值
                    if slot_change.get('is_new_slot', False):
                        state_value = slot_change['after']
                    else:
                        state_value = slot_change['before']

                    threshold_info = self.threshold_inferrer.infer_threshold(
                        param_value, state_value, pattern
                    )

                    # 推断slot语义
                    semantic = self.state_analyzer.infer_slot_semantic(
                        best_corr['slot'], slot_change,
                        attack_info.get('vulnerable_contract', {}).get('name', '')
                    )

                    constraint = self._build_constraint(
                        func_name=func_name,
                        param=param,
                        pattern=pattern,
                        slot=best_corr['slot'],
                        semantic=semantic,
                        state_value=state_value,
                        threshold_info=threshold_info,
                        correlation=best_corr
                    )

                    constraints.append(constraint)
                else:
                    # 没有找到关联，使用最大变化的slot
                    if slot_changes:
                        top_change = slot_changes[0]

                        # 对于新建slot使用after值
                        if top_change.get('is_new_slot', False):
                            state_value = top_change['after']
                        else:
                            state_value = top_change['before']

                        threshold_info = self.threshold_inferrer.infer_threshold(
                            param_value, state_value, pattern
                        )

                        semantic = self.state_analyzer.infer_slot_semantic(
                            top_change['slot'], top_change,
                            attack_info.get('vulnerable_contract', {}).get('name', '')
                        )

                        constraint = self._build_constraint(
                            func_name=func_name,
                            param=param,
                            pattern=pattern,
                            slot=top_change['slot'],
                            semantic=semantic,
                            state_value=state_value,
                            threshold_info=threshold_info,
                            correlation=None
                        )

                        constraints.append(constraint)

        return constraints

    def _estimate_param_value(self, value_expr: str, vuln_address: str) -> Optional[int]:
        """
        估算参数值

        支持的格式:
        - BARL.balanceOf(address(wBARL))
        - 数字字面量
        - 变量名
        """
        value_expr = value_expr.strip()

        # 1. 数字字面量
        if value_expr.isdigit():
            return int(value_expr)

        # 2. balanceOf表达式
        pattern = r'(\w+)\.balanceOf\(address\((\w+)\)\)'
        match = re.search(pattern, value_expr)
        if match:
            token_name = match.group(1)
            holder_name = match.group(2)

            # 从addresses.json获取实际值
            balance = self._get_balance_from_state(token_name, holder_name)
            if balance is not None:
                return balance

            # 如果holder是被攻击合约，使用该合约的storage
            storage = self.state_analyzer.get_contract_storage(vuln_address, before=True)
            if storage:
                # 返回slot 2或3的值作为估计
                for slot in ['2', '3']:
                    if slot in storage:
                        return to_int(storage[slot])

        # 3. 算术表达式
        numbers = re.findall(r'\d+', value_expr)
        if numbers:
            return max(int(n) for n in numbers)

        # 4. 变量名 - 使用默认值
        return 10**18

    def _get_balance_from_state(self, token_name: str, holder_name: str) -> Optional[int]:
        """从状态中获取余额"""
        if not self.state_analyzer.state_before:
            return None

        addresses = self.state_analyzer.state_before.get('addresses', {})

        # 查找token地址
        token_addr = None
        holder_addr = None

        for addr, data in addresses.items():
            name = data.get('name', '')
            if name == token_name or token_name in name or name in token_name:
                token_addr = addr
            if name == holder_name or holder_name in name or name in holder_name:
                holder_addr = addr

        if token_addr and holder_addr:
            # 从token合约的storage中查找holder的余额
            token_storage = self.state_analyzer.get_contract_storage(token_addr, before=True)
            if token_storage:
                # ERC20的balanceOf在slot 0的mapping中
                # 简化：返回一个合理的估计值
                for slot, value in token_storage.items():
                    val = to_int(value)
                    if val > 10**18:  # 找一个大于1 token的值
                        return val

        return None

    def _build_constraint(
        self,
        func_name: str,
        param: Dict,
        pattern: str,
        slot: str,
        semantic: str,
        state_value: int,
        threshold_info: Dict,
        correlation: Optional[Dict]
    ) -> Dict:
        """构建约束对象 - 基于实际关联分析动态生成表达式"""

        # 获取关联信息
        correlation_type = correlation['correlation_type'] if correlation else 'heuristic'
        ratio = correlation.get('ratio', 1.0) if correlation else 1.0
        slot_change = correlation.get('slot_change', {}) if correlation else {}
        change_direction = slot_change.get('change_direction', 'increase')
        is_new_slot = slot_change.get('is_new_slot', False)

        # 变量名 - 改进的参数名提取逻辑
        param_name = self._extract_param_name(param.get('value_expr', 'amount'))
        state_var = semantic if semantic != "unknown" else f"slot_{slot}"

        # 基于关联类型和变化方向生成约束表达式
        constraint_info = self._generate_dynamic_expression(
            param_name=param_name,
            state_var=state_var,
            correlation_type=correlation_type,
            ratio=ratio,
            change_direction=change_direction,
            is_new_slot=is_new_slot,
            state_value=state_value,
            param_value=self._get_param_actual_value(param, slot_change),
            pattern=pattern
        )

        return {
            "function": func_name,
            "signature": f"{func_name}(...)",
            "attack_pattern": pattern,
            "constraint": {
                "type": constraint_info['constraint_type'],
                "expression": constraint_info['expression'],
                "semantics": constraint_info['semantics'],
                "variables": {
                    param_name: {
                        "source": "function_parameter",
                        "index": param['index'],
                        "type": "uint256",
                        "value_expr": param['value_expr']
                    },
                    state_var: {
                        "source": "storage",
                        "slot": slot if slot.startswith('0x') or slot.isdigit() else f"0x{slot}",
                        "type": "uint256",
                        "semantic_name": semantic,
                        "before_value": slot_change.get('before', state_value),
                        "after_value": slot_change.get('after', state_value)
                    }
                },
                "danger_condition": constraint_info['danger_condition'],
                "safe_condition": constraint_info['safe_condition'],
                "threshold_value": constraint_info['threshold_value']
            },
            "analysis": {
                "state_value": state_value,
                "threshold": threshold_info['threshold'],
                "coefficient": threshold_info.get('coefficient'),
                "attack_intensity": threshold_info['attack_intensity'],
                "reasoning": constraint_info['reasoning'],
                "correlation_type": correlation_type,
                "correlation_confidence": correlation['confidence'] if correlation else 0.5,
                "ratio": ratio,
                "change_direction": change_direction
            }
        }

    def _get_param_actual_value(self, param: Dict, slot_change: Dict) -> int:
        """尝试获取参数的实际值"""
        # 如果slot_change有变化量，可以反推
        if slot_change:
            return slot_change.get('change_abs', 0)
        return 0

    def _extract_param_name(self, value_expr: str) -> str:
        """
        从参数表达式中提取规范的参数名

        处理各种情况:
        - BARL.balanceOf(address(wBARL)) -> amount
        - users[i] -> users
        - 1e9 -> amount
        - pseudoTotalPool * 2 - 1 -> pseudoTotalPool
        - depositAmount - 100 -> depositAmount
        - amount << 1 -> amount
        """
        if not value_expr:
            return 'amount'

        value_expr = value_expr.strip()

        # 1. 如果是纯数字或科学计数法，返回默认名
        if re.match(r'^[\d_]+$', value_expr) or re.match(r'^\d+e\d+$', value_expr):
            return 'amount'

        # 2. 如果包含balanceOf，返回amount
        if 'balanceOf' in value_expr:
            return 'amount'

        # 3. 提取第一个有效的变量名（字母开头，包含字母数字下划线）
        # 但排除关键字和常见无意义名称
        tokens = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', value_expr)

        # 排除列表
        exclude = {'address', 'this', 'true', 'false', 'uint256', 'int256',
                   'bytes', 'bytes32', 'i', 'j', 'k', 'e'}

        for token in tokens:
            if token.lower() not in exclude and len(token) > 1:
                return token

        # 4. 如果没有找到有效变量名，返回默认
        return 'amount'

    def _generate_dynamic_expression(
        self,
        param_name: str,
        state_var: str,
        correlation_type: str,
        ratio: float,
        change_direction: str,
        is_new_slot: bool,
        state_value: int,
        param_value: int,
        pattern: str
    ) -> Dict:
        """
        基于实际关联分析动态生成约束表达式

        核心逻辑：
        1. 分析参数值与状态变化的数学关系
        2. 根据变化方向确定约束类型（增加/减少）
        3. 计算实际的阈值而不是硬编码系数
        """

        # 计算实际的危险阈值
        if state_value > 0:
            # 基于实际攻击使用的比例计算阈值
            if param_value > 0:
                attack_ratio = param_value / state_value
                # 安全阈值设为攻击值的一定比例
                safe_ratio = min(attack_ratio * 0.3, 0.5)  # 不超过50%
            else:
                safe_ratio = 0.3
            threshold_value = int(state_value * safe_ratio)
        else:
            # 新建slot，使用after值
            threshold_value = param_value // 2 if param_value > 0 else 0
            safe_ratio = 0.5

        # 根据关联类型生成不同的约束
        if correlation_type == 'direct':
            # 参数直接等于状态变化量
            if change_direction == 'increase':
                # 存入/铸造类：参数导致状态增加
                expression = f"{param_name} > {threshold_value}"
                danger_condition = f"{param_name} >= {state_value}"
                safe_condition = f"{param_name} <= {threshold_value}"
                semantics = f"Direct deposit/mint: parameter directly increases {state_var}"
                reasoning = f"参数直接导致{state_var}增加{param_value}，阈值设为{threshold_value}"
            else:
                # 取出/销毁类：参数导致状态减少
                expression = f"{param_name} > {threshold_value}"
                danger_condition = f"{param_name} >= {state_value}"
                safe_condition = f"{param_name} <= {threshold_value}"
                semantics = f"Direct withdraw/burn: parameter directly decreases {state_var}"
                reasoning = f"参数直接导致{state_var}减少{param_value}，阈值设为{threshold_value}"
            constraint_type = "absolute_threshold"

        elif correlation_type == 'double':
            # 2倍关系，常见于LP操作
            effective_impact = int(param_value * 2)
            threshold_value = int(state_value * 0.25)  # 因为有2倍放大
            expression = f"{param_name} * 2 > {state_var} * 0.5"
            danger_condition = f"{param_name} >= {state_value // 2}"
            safe_condition = f"{param_name} <= {threshold_value}"
            semantics = f"Double impact: parameter has 2x effect on {state_var}"
            reasoning = f"参数有2倍放大效应，实际影响{effective_impact}，阈值设为{threshold_value}"
            constraint_type = "multiplied_threshold"

        elif correlation_type == 'multiple':
            # 循环攻击，多次累积
            # 添加合理性检查：迭代次数上限为10000
            raw_iterations = round(ratio)
            max_iterations = 10000
            if raw_iterations > max_iterations:
                # 如果迭代次数异常大，说明关联分析可能不准确
                # 降级为heuristic处理
                iterations = max_iterations
                # 重新计算更合理的阈值
                threshold_value = int(state_value * 0.3)
                expression = f"{param_name} > {threshold_value}"
                danger_condition = f"{param_name} >= {int(state_value * 0.9)}"
                safe_condition = f"{param_name} <= {threshold_value}"
                semantics = f"High-frequency operation: parameter affects {state_var} with estimated {raw_iterations} iterations (capped)"
                reasoning = f"高频操作，原始迭代{raw_iterations}次超过上限{max_iterations}，使用保守阈值{threshold_value}"
                constraint_type = "capped_iterated_threshold"
            else:
                iterations = raw_iterations
                threshold_value = int(state_value / iterations * 0.3) if iterations > 0 else int(state_value * 0.3)
                expression = f"{param_name} * {iterations} > {state_var} * 0.5"
                danger_condition = f"{param_name} >= {state_value // iterations if iterations > 0 else state_value}"
                safe_condition = f"{param_name} <= {threshold_value}"
                semantics = f"Loop attack: parameter applied {iterations} times affects {state_var}"
                reasoning = f"循环攻击{iterations}次，单次参数{param_value // iterations if iterations > 0 else param_value}，阈值设为{threshold_value}"
                constraint_type = "iterated_threshold"

        elif correlation_type == 'partial':
            # 部分提取，参数小于变化量
            extraction_ratio = ratio  # param / change
            threshold_value = int(state_value * extraction_ratio * 0.5)
            expression = f"{param_name} > {threshold_value}"
            danger_condition = f"{param_name} >= {int(state_value * extraction_ratio)}"
            safe_condition = f"{param_name} <= {threshold_value}"
            semantics = f"Partial extraction: {extraction_ratio:.1%} of {state_var} affected per unit"
            reasoning = f"部分提取模式，提取比例{extraction_ratio:.2f}，阈值设为{threshold_value}"
            constraint_type = "ratio_threshold"

        elif correlation_type == 'amplified':
            # 放大效应，小参数导致大变化（如价格操纵）
            # 添加合理性检查：放大系数上限
            amplification = ratio
            max_amplification = 1000000  # 100万倍
            if amplification > max_amplification:
                # 放大系数异常大，使用保守处理
                amplification = max_amplification
                threshold_value = int(state_value * 0.3)
                expression = f"{param_name} > {threshold_value}"
                danger_condition = f"{param_name} >= {int(state_value * 0.9)}"
                safe_condition = f"{param_name} <= {threshold_value}"
                semantics = f"Extreme amplification: parameter has {ratio:.0f}x effect on {state_var} (capped)"
                reasoning = f"极端放大效应{ratio:.0f}倍超过上限，使用保守阈值{threshold_value}"
                constraint_type = "capped_amplified_threshold"
            else:
                threshold_value = int(state_value / amplification * 0.1)
                expression = f"{param_name} > {threshold_value}"
                danger_condition = f"{param_name} * {int(amplification)} >= {state_var}"
                safe_condition = f"{param_name} <= {threshold_value}"
                semantics = f"Amplified effect: parameter has {amplification:.0f}x amplification on {state_var}"
                reasoning = f"放大效应{amplification:.0f}倍，小参数可导致大变化，阈值设为{threshold_value}"
                constraint_type = "amplified_threshold"

        else:
            # heuristic - 无法确定关联，使用保守估计
            if state_value > 0:
                threshold_value = int(state_value * 0.3)
                expression = f"{param_name} > {threshold_value}"
                danger_condition = f"{param_name} >= {int(state_value * 0.9)}"
                safe_condition = f"{param_name} <= {threshold_value}"
            else:
                threshold_value = param_value // 2 if param_value > 0 else 10**18
                expression = f"{param_name} > {threshold_value}"
                danger_condition = f"{param_name} >= {param_value}"
                safe_condition = f"{param_name} <= {threshold_value}"
            semantics = f"Heuristic constraint based on {pattern} pattern"
            reasoning = f"启发式约束，基于{pattern}模式，阈值设为{threshold_value}"
            constraint_type = "heuristic_threshold"

        return {
            'constraint_type': constraint_type,
            'expression': expression,
            'semantics': semantics,
            'danger_condition': danger_condition,
            'safe_condition': safe_condition,
            'threshold_value': threshold_value,
            'reasoning': reasoning
        }

    def _get_pattern_description(self, pattern: str) -> str:
        """获取攻击模式描述"""
        descriptions = {
            'flashloan_attack': 'Large flashloan exceeding safe threshold',
            'borrow_attack': 'Excessive borrowing depleting liquidity',
            'large_deposit': 'Large deposit potentially manipulating pool',
            'drain_attack': 'Draining significant portion of funds',
            'swap_manipulation': 'Large swap causing price manipulation',
            'collateral_manipulation': 'Collateral manipulation affecting liquidation',
        }
        return descriptions.get(pattern, 'Suspicious operation detected')

    def _generate_heuristic_constraints(self, attack_info: Dict) -> List[Dict]:
        """启发式约束生成（当没有状态差异时的后备方案）"""
        # 复用v1的逻辑
        constraints = []

        for call in attack_info.get('attack_calls', []):
            func_name = call['function']
            params = call['parameters']
            pattern = self._identify_attack_pattern(func_name)

            if not pattern:
                continue

            dynamic_params = [p for p in params if p['is_dynamic'] and p['type'] == 'uint256']

            for param in dynamic_params:
                constraint = {
                    "function": func_name,
                    "signature": f"{func_name}(...)",
                    "attack_pattern": pattern,
                    "constraint": {
                        "type": "inequality",
                        "expression": f"amount > state * 0.5",
                        "semantics": self._get_pattern_description(pattern),
                        "variables": {
                            "amount": {
                                "source": "function_parameter",
                                "index": param['index'],
                                "type": "uint256",
                                "value_expr": param['value_expr']
                            },
                            "state": {
                                "source": "storage",
                                "slot": "0x2",
                                "type": "uint256",
                                "semantic_name": "estimated_state"
                            }
                        },
                        "danger_condition": "amount > state * 0.5",
                        "safe_condition": "amount <= state * 0.1"
                    },
                    "analysis": {
                        "state_value": None,
                        "threshold": None,
                        "coefficient": 0.5,
                        "attack_intensity": None,
                        "reasoning": "Heuristic constraint (no state diff available)",
                        "correlation_type": "heuristic",
                        "correlation_confidence": 0.3
                    }
                }
                constraints.append(constraint)

        return constraints


# =============================================================================
# 主提取器
# =============================================================================

class ConstraintExtractorV2:
    """改进版约束提取器"""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.extracted_dir = repo_root / "extracted_contracts"
        self.scripts_dir = repo_root / "src" / "test"

    def extract_single(self, protocol_name: str, year_month: str) -> Optional[Dict]:
        """提取单个协议的约束"""
        logger.info(f"开始提取约束 (V2): {protocol_name}")

        # 定位文件
        protocol_dir = self.extracted_dir / year_month / protocol_name
        script_path = self.scripts_dir / year_month / f"{protocol_name}.sol"

        if not script_path.exists():
            logger.warning(f"攻击脚本不存在: {script_path}")
            return None

        if not protocol_dir.exists():
            logger.warning(f"协议目录不存在: {protocol_dir}")
            return None

        # 解析攻击脚本
        parser = AttackScriptParser(script_path)
        attack_info = parser.parse()

        vulnerable_contract = attack_info.get('vulnerable_contract', {})
        vuln_address = vulnerable_contract.get('address')

        logger.info(f"  被攻击合约: {vulnerable_contract.get('name')} ({vuln_address})")
        logger.info(f"  识别到 {len(attack_info.get('attack_calls', []))} 个函数调用")

        # 状态差异分析
        state_analyzer = StateDiffAnalyzer(protocol_dir)

        if vuln_address:
            slot_changes = state_analyzer.analyze_slot_changes(vuln_address)
            logger.info(f"  检测到 {len(slot_changes)} 个slot变化")
        else:
            slot_changes = []

        # 生成约束
        constraint_gen = ConstraintGeneratorV2(state_analyzer)

        if vuln_address:
            constraints = constraint_gen.generate(attack_info, vuln_address)
        else:
            constraints = constraint_gen._generate_heuristic_constraints(attack_info)

        logger.success(f"  生成约束: {len(constraints)} 个")

        # 构建结果
        loop_info = attack_info.get('loop_info') or {}

        result = {
            "protocol": protocol_name,
            "year_month": year_month,
            "vulnerable_contract": vulnerable_contract,
            "constraints": constraints,
            "state_analysis": {
                "slot_changes": [
                    {
                        "slot": c['slot'],
                        "before": c['before'],
                        "after": c['after'],
                        "change_pct": round(c['change_pct'], 2),
                        "is_new_slot": c.get('is_new_slot', False)
                    }
                    for c in slot_changes[:5]  # 只保留前5个
                ],
                "total_changed_slots": len(slot_changes)
            },
            "attack_metadata": {
                "loop_count": loop_info.get('count', 1),
                "total_calls": len(attack_info.get('attack_calls', []))
            },
            "metadata": {
                "extraction_version": "2.0.0",
                "generated_by": "extract_param_state_constraints_v2.py",
                "improvements": [
                    "Based on actual state diff analysis",
                    "Dynamic threshold inference",
                    "Parameter-slot correlation"
                ]
            }
        }

        return result

    def save_result(self, result: Dict, protocol_name: str, year_month: str):
        """保存结果"""
        if not result:
            return

        output_path = self.extracted_dir / year_month / protocol_name / "constraint_rules_v2.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)

        logger.success(f"约束规则已保存: {output_path}")

    def batch_extract(self, year_month_filter: str = None) -> Dict[str, Dict]:
        """批量提取"""
        results = {}

        year_month_dirs = []
        if year_month_filter:
            filter_dir = self.extracted_dir / year_month_filter
            if filter_dir.exists():
                year_month_dirs = [filter_dir]
        else:
            year_month_dirs = [d for d in self.extracted_dir.iterdir() if d.is_dir()]

        for year_month_dir in year_month_dirs:
            year_month = year_month_dir.name

            for protocol_dir in sorted(year_month_dir.iterdir()):
                if not protocol_dir.is_dir():
                    continue

                protocol_name = protocol_dir.name

                try:
                    result = self.extract_single(protocol_name, year_month)
                    if result is not None:
                        self.save_result(result, protocol_name, year_month)
                        results[protocol_name] = result
                except Exception as e:
                    logger.error(f"处理 {protocol_name} 时出错: {e}")
                    import traceback
                    traceback.print_exc()

        return results


# =============================================================================
# 主函数
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="从攻击PoC中提取参数-状态约束关系 (V2改进版)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 单个协议
  python extract_param_state_constraints_v2.py --protocol BarleyFinance_exp --year-month 2024-01

  # 批量处理
  python extract_param_state_constraints_v2.py --batch --filter 2024-01

改进:
  - 基于实际状态差异分析
  - 动态阈值推断
  - 参数-slot关联分析
        """
    )

    parser.add_argument('--protocol', help='协议名称')
    parser.add_argument('--year-month', help='年月')
    parser.add_argument('--batch', action='store_true', help='批量模式')
    parser.add_argument('--filter', help='年月过滤器')
    parser.add_argument('--output', help='自定义输出路径')

    args = parser.parse_args()

    repo_root = Path(__file__).parent
    extractor = ConstraintExtractorV2(repo_root)

    if args.batch:
        logger.info("=== 批量提取模式 (V2) ===")
        results = extractor.batch_extract(year_month_filter=args.filter)

        # 统计
        total = len(results)
        with_constraints = sum(1 for r in results.values() if r.get('constraints'))
        total_constraints = sum(len(r.get('constraints', [])) for r in results.values())

        logger.success(f"\n总计处理: {total} 个协议")
        logger.success(f"生成约束: {total_constraints} 个 ({with_constraints} 个协议)")

    elif args.protocol and args.year_month:
        logger.info("=== 单协议提取模式 (V2) ===")
        result = extractor.extract_single(args.protocol, args.year_month)

        if result:
            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False, default=str)
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
