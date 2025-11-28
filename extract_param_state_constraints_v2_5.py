#!/usr/bin/env python3
"""
参数-状态约束提取器 V2.5 (Parameter-State Constraint Extractor V2.5)

混合增强版本 - 集成V3的Storage布局推断和符号执行求值

核心改进:
1. 分析攻击前后状态差异，找到真正受影响的slot
2. 关联函数参数与状态slot变化
3. 从实际攻击行为推断阈值系数
4. 动态识别slot语义
5. [V3] keccak256逆向推断mapping结构
6. [V3] 符号执行精确求值参数表达式

作者: FirewallOnchain Team
版本: 2.5.0
日期: 2025-01-21
"""

import argparse
import json
import re
import sys
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal, getcontext
from collections import defaultdict
from datetime import datetime
from eth_hash.auto import keccak

# 设置高精度
getcontext().prec = 78

# =============================================================================
# V3组件条件导入
# =============================================================================
try:
    from extract_param_state_constraints_v3 import (
        StorageLayoutInferrer,
        SymbolicParameterEvaluator,
        ContractProxy,
        StorageLayout,
        to_int as v3_to_int
    )
    V3_AVAILABLE = True
    V3_IMPORT_ERROR = None
except ImportError as e:
    V3_AVAILABLE = False
    V3_IMPORT_ERROR = str(e)
    # 定义占位类型避免类型错误
    StorageLayoutInferrer = None
    SymbolicParameterEvaluator = None
    ContractProxy = None
    StorageLayout = None

# =============================================================================
# Slither集成条件导入
# =============================================================================
try:
    import sys
    from pathlib import Path as PathLib
    # 添加项目根目录到路径
    firewall_root = PathLib(__file__).parent.parent
    if str(firewall_root) not in sys.path:
        sys.path.insert(0, str(firewall_root))

    from scripts.tools.slither_integration import (
        SlitherFunctionAnalyzer,
        SlitherCallGraphBuilder,
        SlitherStorageAnalyzer,
        SlitherContractResolver
    )
    SLITHER_AVAILABLE = True
    SLITHER_IMPORT_ERROR = None
except ImportError as e:
    SLITHER_AVAILABLE = False
    SLITHER_IMPORT_ERROR = str(e)
    # 定义占位类型
    SlitherFunctionAnalyzer = None
    SlitherCallGraphBuilder = None
    SlitherStorageAnalyzer = None
    SlitherContractResolver = None

# 配置日志
class Logger:
    """增强的彩色日志器，支持文件输出和耗时统计"""
    COLORS = {
        'info': '\033[0;34m',
        'success': '\033[0;32m',
        'warning': '\033[1;33m',
        'error': '\033[0;31m',
        'debug': '\033[0;36m',
        'timer': '\033[0;35m',  # 紫色用于耗时信息
        'reset': '\033[0m'
    }

    def __init__(self, log_file=None):
        self.log_file = log_file
        self.file_handler = None
        self.timers = {}  # 存储各个任务的开始时间

        if self.log_file:
            # 创建日志目录
            log_path = Path(self.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # 配置文件日志
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s [%(levelname)s] %(message)s',
                handlers=[
                    logging.FileHandler(self.log_file, encoding='utf-8'),
                ]
            )
            self.file_handler = logging.getLogger()

    def _log_to_file(self, level, msg):
        """写入日志文件"""
        if self.file_handler:
            if level == 'info':
                self.file_handler.info(msg)
            elif level == 'success':
                self.file_handler.info(f"✓ {msg}")
            elif level == 'warning':
                self.file_handler.warning(msg)
            elif level == 'error':
                self.file_handler.error(msg)
            elif level == 'debug':
                self.file_handler.debug(msg)
            elif level == 'timer':
                self.file_handler.info(f"⏱ {msg}")

    def info(self, msg):
        print(f"{self.COLORS['info']}[INFO]{self.COLORS['reset']} {msg}")
        self._log_to_file('info', msg)

    def success(self, msg):
        print(f"{self.COLORS['success']}[SUCCESS]{self.COLORS['reset']} {msg}")
        self._log_to_file('success', msg)

    def warning(self, msg):
        print(f"{self.COLORS['warning']}[WARNING]{self.COLORS['reset']} {msg}")
        self._log_to_file('warning', msg)

    def error(self, msg):
        print(f"{self.COLORS['error']}[ERROR]{self.COLORS['reset']} {msg}")
        self._log_to_file('error', msg)

    def debug(self, msg):
        print(f"{self.COLORS['debug']}[DEBUG]{self.COLORS['reset']} {msg}")
        self._log_to_file('debug', msg)

    def timer_start(self, task_name):
        """开始计时"""
        self.timers[task_name] = time.time()
        msg = f"开始: {task_name}"
        print(f"{self.COLORS['timer']}[⏱]{self.COLORS['reset']} {msg}")
        self._log_to_file('timer', msg)

    def timer_end(self, task_name):
        """结束计时并显示耗时"""
        if task_name in self.timers:
            elapsed = time.time() - self.timers[task_name]
            msg = f"完成: {task_name} - 耗时: {self._format_time(elapsed)}"
            print(f"{self.COLORS['timer']}[⏱]{self.COLORS['reset']} {msg}")
            self._log_to_file('timer', msg)
            del self.timers[task_name]
            return elapsed
        return 0

    def _format_time(self, seconds):
        """格式化时间显示"""
        if seconds < 1:
            return f"{seconds*1000:.0f}ms"
        elif seconds < 60:
            return f"{seconds:.2f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}m {secs:.1f}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = seconds % 60
            return f"{hours}h {minutes}m {secs:.0f}s"

logger = Logger()

# V3组件可用性日志
if V3_AVAILABLE:
    logger.success("V3增强组件已加载 (Storage推断 + 符号执行)")
else:
    logger.warning(f"V3组件不可用,使用V2 fallback: {V3_IMPORT_ERROR}")
    logger.info("提示: 运行 'python3 extract_param_state_constraints_v3.py --help' 检查V3安装")

# Slither集成可用性日志
if SLITHER_AVAILABLE:
    logger.success("✓ Slither静态分析工具已加载 (精确AST解析)")
else:
    logger.warning(f"Slither不可用,使用正则表达式fallback: {SLITHER_IMPORT_ERROR}")
    logger.info("提示: 运行 'pip install slither-analyzer' 安装Slither")


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
# V3→V2格式转换函数
# =============================================================================

def convert_storage_layout_to_v2(layout, confidence_threshold=0.7) -> Dict[str, str]:
    """
    将V3的StorageLayout转换为V2的slot→语义映射

    Args:
        layout: V3的StorageLayout对象
        confidence_threshold: 置信度阈值,低于此值的推断将被忽略

    Returns:
        Dict[str, str]: slot → 语义名称的映射
    """
    if not V3_AVAILABLE or layout is None:
        return {}

    slot_semantic = {}

    # 转换普通变量
    for slot, var_info in layout.variables.items():
        if var_info.confidence >= confidence_threshold:
            slot_semantic[slot] = var_info.name
            logger.info(f"  V3推断: slot {slot} → {var_info.name} (置信度{var_info.confidence:.2f})")
        else:
            logger.warning(f"  V3推断置信度过低: slot {slot} → {var_info.name} (置信度{var_info.confidence:.2f}), 跳过")

    # 转换mapping (使用base_slot作为标识)
    for base_slot_str, mapping_info in layout.mappings.items():
        # 将base slot添加到映射中
        slot_semantic[base_slot_str] = mapping_info.name
        logger.info(f"  V3推断: slot {base_slot_str} (base) → {mapping_info.name} mapping ({len(mapping_info.known_keys)} keys)")

    return slot_semantic


def filter_v3_layout_by_confidence(layout, threshold=0.7):
    """
    过滤V3 StorageLayout中低置信度的推断

    Args:
        layout: V3的StorageLayout对象
        threshold: 置信度阈值

    Returns:
        过滤后的StorageLayout (新对象)
    """
    if not V3_AVAILABLE or layout is None:
        return None

    # 创建新的StorageLayout对象
    filtered = StorageLayout(contract_address=layout.contract_address)

    # 过滤variables
    for slot, var_info in layout.variables.items():
        if var_info.confidence >= threshold:
            filtered.variables[slot] = var_info

    # mappings不过滤(它们基于keccak256逆向,要么成功要么失败)
    filtered.mappings = layout.mappings.copy()

    return filtered


# =============================================================================
# 状态差异分析器
# =============================================================================

class StateDiffAnalyzer:
    """分析攻击前后的状态差异"""

    def __init__(self, protocol_dir: Path, firewall_config=None):
        self.protocol_dir = protocol_dir
        self.firewall_config = firewall_config  # 新增：防火墙配置
        self.state_before = self._load_json("attack_state.json")
        self.state_after = self._load_json("attack_state_after.json")
        self.addresses_info = self._load_json("addresses.json")

        # V3增强: 初始化Storage布局推断器
        if V3_AVAILABLE and self.addresses_info:
            try:
                self.layout_inferrer = StorageLayoutInferrer(self, self.addresses_info)
                logger.info("V3 StorageLayoutInferrer已初始化")
            except Exception as e:
                logger.warning(f"V3 StorageLayoutInferrer初始化失败: {e}, 回退到V2")
                self.layout_inferrer = None
        else:
            self.layout_inferrer = None
            if not V3_AVAILABLE:
                logger.debug("V3不可用,跳过StorageLayoutInferrer初始化")

    def _load_json(self, filename: str) -> Optional[Dict]:
        file_path = self.protocol_dir / filename
        if not file_path.exists():
            return None
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                # 如果是addresses.json且为列表格式,转换为字典
                if filename == "addresses.json" and isinstance(data, list):
                    return {item['address'].lower(): item for item in data if 'address' in item}
                return data
        except Exception as e:
            logger.warning(f"加载{filename}失败: {e}")
            return None

    def get_analysis_targets(self) -> List[str]:
        """
        获取需要分析状态的合约地址列表

        优先级:
        1. 如果有防火墙配置，优先使用配置中的被保护合约地址
        2. 检查配置的合约是否有状态变化，如果没有则回退到动态检测
        3. 动态检测：分析所有有状态变化的合约

        Returns:
            合约地址列表（小写）
        """
        # 优先使用防火墙配置
        if self.firewall_config:
            addresses = self.firewall_config.get_contract_addresses()
            logger.info(f"  防火墙配置指定: {len(addresses)} 个合约")

            # 检查这些合约是否有状态变化
            valid_addresses = []
            for addr in addresses:
                slot_changes = self.analyze_slot_changes(addr)
                if slot_changes:
                    valid_addresses.append(addr.lower())

            if valid_addresses:
                logger.info(f"  使用防火墙配置中有状态变化的合约: {len(valid_addresses)} 个")
                return valid_addresses
            else:
                logger.warning(f"  防火墙配置的合约都没有状态变化，回退到动态检测")
                # 继续执行动态检测

        # 动态检测：找出所有有状态变化的合约
        changed_contracts = []
        if not self.state_before or not self.state_after:
            return changed_contracts

        before_addrs = self.state_before.get('addresses', {})
        after_addrs = self.state_after.get('addresses', {})

        for addr in before_addrs:
            if addr not in after_addrs:
                continue

            before_storage = before_addrs[addr].get('storage', {})
            after_storage = after_addrs[addr].get('storage', {})

            # 检查是否有任何slot变化
            all_slots = set(before_storage.keys()) | set(after_storage.keys())
            for slot in all_slots:
                if before_storage.get(slot) != after_storage.get(slot):
                    changed_contracts.append(addr.lower())
                    logger.debug(f"  检测到状态变化: {addr[:12]}...")
                    break

        if changed_contracts:
            logger.info(f"  动态检测到 {len(changed_contracts)} 个合约有状态变化")
        else:
            logger.warning(f"  未检测到任何合约的状态变化")

        return changed_contracts

    def _find_address_by_name(self, search_name: str) -> Optional[str]:
        """
        增强的名称查找 - 使用aliases支持模糊匹配

        查找优先级:
        1. 精确匹配 name 字段
        2. 精确匹配 aliases 中的任意别名
        3. 精确匹配 symbol 字段
        4. 部分匹配 name (search_name in name)
        5. 部分匹配 aliases

        Args:
            search_name: 要查找的名称(如 'wBARL', 'IwBARL', 'BARL')

        Returns:
            匹配的地址(小写),如果未找到返回None
        """
        # 添加空值检查 - 防御性编程
        if not search_name or not self.addresses_info:
            logger.debug(f"search_name为空或addresses_info不可用: search_name={search_name}")
            return None

        # 标准化搜索名称(去除大小写影响)
        search_lower = search_name.lower()

        # 第一轮: 精确匹配
        for addr, info in self.addresses_info.items():
            # 1. 精确匹配 name
            name = info.get('name', '')
            if name and name.lower() == search_lower:
                logger.debug(f"精确匹配name: {search_name} → {addr}")
                return addr

            # 2. 精确匹配 symbol
            symbol = info.get('symbol', '')
            if symbol and symbol.lower() == search_lower:
                logger.debug(f"精确匹配symbol: {search_name} → {addr}")
                return addr

            # 3. 精确匹配 aliases
            aliases = info.get('aliases', [])
            if aliases:
                for alias in aliases:
                    if alias and alias.lower() == search_lower:
                        logger.debug(f"精确匹配alias: {search_name} → {alias} → {addr}")
                        return addr

        # 第二轮: 部分匹配(包含关系)
        for addr, info in self.addresses_info.items():
            # 4. 部分匹配 name
            name = info.get('name', '')
            if name and (search_lower in name.lower() or name.lower() in search_lower):
                logger.debug(f"部分匹配name: {search_name} ~ {name} → {addr}")
                return addr

            # 5. 部分匹配 aliases
            aliases = info.get('aliases', [])
            if aliases:
                for alias in aliases:
                    if alias and (search_lower in alias.lower() or alias.lower() in search_lower):
                        logger.debug(f"部分匹配alias: {search_name} ~ {alias} → {addr}")
                        return addr

        logger.debug(f"未找到匹配: {search_name}")
        return None

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
        # ERC20特殊补全: 如为ERC20合约，尝试补充 balanceOf 映射槽变化
        changes = self._augment_erc20_balance_slots(address, storage_before, storage_after, changes)

        return sorted(changes, key=lambda x: x['change_abs'], reverse=True)

    def _augment_erc20_balance_slots(self, contract_addr: str, storage_before: Dict, storage_after: Dict, changes: List[Dict]) -> List[Dict]:
        """
        针对ERC20合约补充balanceOf映射槽位的变化（如果已存在则跳过）
        仅当addresses.json标记为ERC20且能定位到持币人对应的mapping槽位时才添加。
        """
        info = self.addresses_info.get(contract_addr.lower()) if self.addresses_info else None
        name = (info.get('name', '') if info else '').lower()
        aliases = [a.lower() for a in info.get('aliases', [])] if info and info.get('aliases') else []

        # 判断是否ERC20
        if not (('erc20' in name) or any('erc20' in a for a in aliases)):
            return changes

        existing_slots = {c['slot'] for c in changes}

        # 选取关键地址（受害者/攻击者/攻击合约）
        candidate_holders = []
        for addr, addr_info in (self.addresses_info or {}).items():
            holder_name = (addr_info.get('name') or '').lower()
            if any(key in holder_name for key in ['victim', 'attacker', 'attack_contract', 'exploiter']):
                candidate_holders.append(addr.lower())

        if not candidate_holders:
            return changes

        def _slot_key(addr: str, base_slot: int) -> str:
            h = keccak(int(addr, 16).to_bytes(32, 'big') + base_slot.to_bytes(32, 'big'))
            return str(int.from_bytes(h, 'big'))

        for holder in candidate_holders:
            matched_slot = None
            matched_base = None
            for base in range(0, 5):
                key = _slot_key(holder, base)
                if key in storage_before or key in storage_after:
                    matched_slot = key
                    matched_base = base
                    break

            if matched_slot and matched_slot not in existing_slots:
                before_val = to_int(storage_before.get(matched_slot, '0x0'))
                after_val = to_int(storage_after.get(matched_slot, '0x0'))
                if before_val != after_val:
                    change = after_val - before_val
                    change_pct = abs(change) / before_val * 100 if before_val else 100.0
                    changes.append({
                        'slot': matched_slot,
                        'before': before_val,
                        'after': after_val,
                        'change': change,
                        'change_abs': abs(change),
                        'change_pct': change_pct,
                        'change_direction': 'increase' if change > 0 else 'decrease',
                        'is_new_slot': before_val == 0 and after_val != 0,
                        'is_cleared_slot': before_val != 0 and after_val == 0,
                        'semantic_hint': f'erc20_balance_slot_base_{matched_base}'
                    })
            # 如果找不到匹配槽位，增加一个合成slot以保证监控覆盖
            elif not matched_slot:
                synthetic_slot = _slot_key(holder, 0)
                if synthetic_slot not in existing_slots:
                    changes.append({
                        'slot': synthetic_slot,
                        'before': 0,
                        'after': 1,
                        'change': 1,
                        'change_abs': 1,
                        'change_pct': 100.0,
                        'change_direction': 'increase',
                        'is_new_slot': True,
                        'is_cleared_slot': False,
                        'semantic_hint': 'erc20_balance_synthetic_base_0'
                    })

        return changes

    def get_token_balance(self, token_name: str, holder_name: str) -> Optional[int]:
        """
        从addresses.json获取token余额

        Args:
            token_name: token名称 (如 'BARL', 'wBARL', 'IwBARL')
            holder_name: 持有者名称 (如 'wBARL', 'Attacker', 'IwBARL')
        """
        if not self.addresses_info:
            return None

        # 使用增强的名称查找(支持aliases)
        token_addr = self._find_address_by_name(token_name)
        holder_addr = self._find_address_by_name(holder_name)

        if not token_addr or not holder_addr:
            if not token_addr:
                logger.debug(f"未找到token地址: {token_name}")
            if not holder_addr:
                logger.debug(f"未找到holder地址: {holder_name}")
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
        推断slot的语义 - 优先使用V3布局推断，回退到V2启发式方法

        基于以下线索:
        1. [V3] Storage布局推断器的动态分析
        2. 合约源码中的状态变量声明
        3. slot索引
        4. 变化模式 (增加/减少)
        5. 变化幅度
        """
        slot_int = int(slot) if slot.isdigit() else int(slot, 16) if slot.startswith('0x') else -1

        # V3增强: 优先使用StorageLayoutInferrer
        if self.layout_inferrer and V3_AVAILABLE:
            try:
                # 使用增强的名称查找(支持aliases)
                contract_addr = self._find_address_by_name(contract_name)

                if contract_addr:
                    # 使用V3推断布局
                    layout = self.layout_inferrer.infer_layout(contract_addr)

                    # 尝试从布局中获取语义
                    semantic = layout.get_semantic(slot)
                    if semantic:
                        logger.debug(f"V3推断slot {slot} → {semantic}")
                        return semantic

                    # 如果V3无法推断,记录并回退到V2
                    logger.debug(f"V3无法推断slot {slot}, 回退到V2启发式方法")
            except Exception as e:
                logger.debug(f"V3推断失败: {e}, 回退到V2")

        # 1. 尝试从源码获取语义 (V2原有逻辑)
        if hasattr(self, '_storage_layout_cache'):
            if slot_int in self._storage_layout_cache:
                return self._storage_layout_cache[slot_int]
        else:
            # 初始化缓存并尝试解析
            self._storage_layout_cache = {}
            if self.protocol_dir and contract_name:
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

from dataclasses import dataclass
from collections import deque

@dataclass
class FunctionInfo:
    """函数信息数据类"""
    name: str
    visibility: str  # public/external/internal/private
    start_pos: int   # 函数体起始位置
    end_pos: int     # 函数体结束位置
    body: str        # 函数体代码
    internal_calls: List[str] = None  # 调用的内部函数
    external_calls: List[Dict] = None  # 外部合约调用

    def __post_init__(self):
        if self.internal_calls is None:
            self.internal_calls = []
        if self.external_calls is None:
            self.external_calls = []


class AttackScriptParser:
    """攻击脚本解析器 - 增强版: 支持回调函数识别和调用图遍历"""

    # ==========================================================================
    # 回调函数模式库 - 按协议分类的闪电贷回调函数
    # ==========================================================================
    CALLBACK_PATTERNS = {
        # DODO/DPP系列
        'dodo': [
            'DPPFlashLoanCall',
            'DVMFlashLoanCall',
            'DSPFlashLoanCall',
            'DPPOracleFlashLoanCall',
        ],
        # Uniswap V2及其分叉 (PancakeSwap, SushiSwap等)
        'uniswap_v2': [
            'pancakeCall',
            'uniswapV2Call',
            'sushiCall',
            'waultSwapCall',
            'BiswapCall',
            'apeswapCall',
        ],
        # Uniswap V3及Algebra协议
        'uniswap_v3': [
            'uniswapV3FlashCallback',
            'uniswapV3SwapCallback',
            'uniswapV3MintCallback',
            'algebraFlashCallback',
            'algebraSwapCallback',
            'algebraMintCallback',
            'camelotSwapCallback',
            'pancakeV3FlashCallback',
            'pancakeV3SwapCallback',
        ],
        # Balancer
        'balancer': [
            'receiveFlashLoan',
        ],
        # AAVE
        'aave': [
            'executeOperation',
            'onFlashLoan',  # EIP-3156标准
        ],
        # Curve
        'curve': [
            'exchange_callback',
        ],
        # ERC标准回调
        'erc': [
            'onERC721Received',
            'onERC1155Received',
            'onERC1155BatchReceived',
            'tokensReceived',  # ERC777
        ],
        # fallback/receive (特殊处理)
        'fallback': [
            'fallback',
            'receive',
        ],
    }

    # Solidity关键字 - 用于过滤内部调用识别
    SOLIDITY_KEYWORDS = {
        'require', 'assert', 'revert', 'emit', 'delete', 'new',
        'if', 'else', 'while', 'for', 'do', 'return', 'break', 'continue',
        'this', 'super', 'msg', 'tx', 'block', 'abi', 'type',
        'true', 'false', 'keccak256', 'sha256', 'ecrecover',
        'addmod', 'mulmod', 'selfdestruct', 'log0', 'log1', 'log2', 'log3', 'log4',
    }

    # Solidity内置类型 - 用于过滤类型转换
    SOLIDITY_TYPES = {
        'uint', 'uint8', 'uint16', 'uint32', 'uint64', 'uint128', 'uint256',
        'int', 'int8', 'int16', 'int32', 'int64', 'int128', 'int256',
        'address', 'bool', 'bytes', 'bytes32', 'bytes4', 'bytes20',
        'string', 'payable',
    }

    def __init__(self, script_path: Path, use_slither: bool = True):
        self.script_path = script_path
        self.script_content = script_path.read_text()
        # 缓存解析结果
        self._functions_cache: List[FunctionInfo] = None
        self._call_graph_cache: Dict[str, List[str]] = None

        # Slither集成
        self.use_slither = use_slither and SLITHER_AVAILABLE
        self.slither_func_analyzer = None
        self.slither_callgraph_builder = None

        if self.use_slither:
            try:
                logger.debug(f"初始化Slither分析器: {script_path}")
                self.slither_func_analyzer = SlitherFunctionAnalyzer(str(script_path))
                self.slither_callgraph_builder = SlitherCallGraphBuilder(str(script_path))
                logger.info("✓ 使用Slither进行精确AST解析")
            except Exception as e:
                logger.warning(f"Slither初始化失败,回退到正则表达式: {e}")
                self.use_slither = False
                self.slither_func_analyzer = None
                self.slither_callgraph_builder = None

    def parse(self) -> Dict:
        """
        解析攻击脚本 - 增强版

        新增:
        - 回调函数识别
        - 调用图遍历
        - 收集所有可达函数的外部调用
        """
        logger.timer_start(f"脚本解析: {self.script_path.name}")

        # 收集所有外部调用(使用新的调用图遍历)
        all_external_calls = self._collect_all_external_calls()

        # 获取被攻击合约信息
        vuln_contract = self._extract_vulnerable_contract()

        # 将外部调用转换为attack_calls格式
        attack_calls = self._convert_external_calls_to_attack_calls(
            all_external_calls, vuln_contract
        )

        # 获取回调函数信息
        callbacks = self._find_callbacks()

        result = {
            "vulnerable_contract": vuln_contract,
            "attack_calls": attack_calls,
            "loop_info": self._extract_loop_info(),
            # 新增: 元数据
            "metadata": {
                "total_functions": len(self._functions_cache or []),
                "callback_functions": [cb['name'] for cb in callbacks],
                "entry_points": ['testExploit'] + [cb['name'] for cb in callbacks],
            }
        }

        logger.timer_end(f"脚本解析: {self.script_path.name}")
        return result

    def _convert_external_calls_to_attack_calls(
        self,
        external_calls: List[Dict],
        vuln_contract: Dict
    ) -> List[Dict]:
        """
        将外部调用转换为attack_calls格式

        Args:
            external_calls: 外部调用列表
            vuln_contract: 被攻击合约信息

        Returns:
            attack_calls格式的列表
        """
        attack_calls = []

        for call in external_calls:
            func_name = call['function']

            # 尝试解析合约地址
            contract_address = None
            contract_name = None

            if call['type'] == 'direct':
                var_name = call['contract_var']
                contract_address = self._resolve_address_from_var(var_name)
                contract_name = var_name
            elif call['type'] == 'interface':
                addr_expr = call['address_expr']
                # 尝试从表达式中提取变量名
                if re.match(r'^[a-zA-Z_]\w*$', addr_expr):
                    contract_address = self._resolve_address_from_var(addr_expr)
                    contract_name = addr_expr
                elif addr_expr.startswith('0x'):
                    contract_address = addr_expr.lower()
                    contract_name = call.get('interface', 'Unknown')

            # 提取参数(从函数调用位置重新解析)
            params = self._extract_params_for_call(call)

            attack_calls.append({
                "function": func_name,
                "signature": f"{func_name}({','.join([p['type'] for p in params])})",
                "parameters": params,
                "contract_address": contract_address,
                "contract_name": contract_name,
                "source_function": call.get('source_function', 'unknown'),
                "line_number": 0  # 暂时不追踪行号
            })

        logger.info(f"  转换为 {len(attack_calls)} 个attack_calls")
        return attack_calls

    def _extract_params_for_call(self, call: Dict) -> List[Dict]:
        """
        为外部调用提取参数信息

        Args:
            call: 外部调用信息

        Returns:
            参数列表
        """
        # 构建搜索模式
        func_name = call['function']

        if call['type'] == 'direct':
            var_name = call['contract_var']
            pattern = rf'{var_name}\.{func_name}\s*\('
        else:
            # interface调用
            pattern = rf'\.{func_name}\s*\('

        match = re.search(pattern, self.script_content, re.DOTALL)
        if not match:
            return []

        # 从匹配位置开始，提取平衡括号内容
        start_pos = match.end() - 1  # 指向 '('
        params_str = self._extract_balanced_parens_from_pos(start_pos)
        return self._parse_parameters(func_name, params_str)

    def _extract_balanced_parens_content(self, content: str) -> str:
        """提取平衡括号内容(处理嵌套)"""
        result = ""
        depth = 0

        for char in content:
            if char == '(':
                depth += 1
                result += char
            elif char == ')':
                if depth == 0:
                    break
                depth -= 1
                result += char
            else:
                result += char

        return result.strip()

    def _extract_balanced_parens_from_pos(self, start_pos: int) -> str:
        """从script_content的指定位置(指向'(')提取平衡括号内的内容"""
        result = ""
        depth = 0
        started = False

        for i in range(start_pos, len(self.script_content)):
            ch = self.script_content[i]
            if ch == '(':
                depth += 1
                if started:
                    result += ch
                else:
                    started = True
                continue
            if ch == ')':
                depth -= 1
                if depth == 0:
                    break
                result += ch
                continue
            if started:
                result += ch

        return result.strip()

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
            # 将常见类型和数组类型都视为需要分析的动态参数
            dynamic_types = {'uint256', 'int256', 'uint8', 'address', 'bool', 'bytes', 'bytes32', 'address[]', 'uint256[]', 'uint8[]', 'bytes[]'}
            is_dynamic = param_type in dynamic_types

            seeds = []
            if param_type.endswith('[]'):
                seeds = self._extract_array_seeds(param)

            result.append({
                "index": idx,
                "type": param_type,
                "value_expr": param,
                "is_dynamic": is_dynamic,
                "seeds": seeds
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
            # 简单推断数组元素类型
            if 'address' in param_expr:
                return 'address[]'
            if any(token in param_expr for token in ['uint8', 'perc', 'ratio']):
                return 'uint8[]'
            return 'uint256[]'
        elif re.search(rf'{re.escape(param_expr)}\s*\[\s*\d+\s*\]', self.script_content):
            # 根据赋值语句推断数组类型
            seeds = self._extract_array_seeds(param_expr)
            if seeds:
                has_addr = any('0x' in s.lower() or 'address(' in s for s in seeds)
                if has_addr:
                    return 'address[]'
                # 如果所有数字 <=255 则视为uint8[]
                try:
                    numbers = [int(re.findall(r'\d+', s)[0]) for s in seeds if re.findall(r'\d+', s)]
                    if numbers and all(n <= 255 for n in numbers):
                        return 'uint8[]'
                except Exception:
                    pass
            return 'uint256[]'
        elif param_expr.startswith('"') or param_expr.startswith("'"):
            return 'bytes'
        elif any(name in param_expr.lower() for name in ['amount', 'value', 'count']):
            return 'uint256'
        else:
            return 'uint256'  # 默认为uint256

    def _extract_array_seeds(self, array_name: str) -> List[str]:
        """从脚本中提取数组初始化的元素种子"""
        seeds = []
        pattern = rf'{re.escape(array_name)}\s*\[\s*\d+\s*\]\s*=\s*([^;]+);'
        for match in re.findall(pattern, self.script_content):
            seeds.append(match.strip())
        return seeds

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

    # ==========================================================================
    # 阶段1: 回调函数识别
    # ==========================================================================

    def _find_callbacks(self) -> List[Dict]:
        """
        扫描脚本识别所有回调函数

        返回: [{'name': 'DPPFlashLoanCall', 'protocol': 'dodo', 'position': 123}, ...]
        """
        callbacks = []

        for protocol, func_names in self.CALLBACK_PATTERNS.items():
            for func_name in func_names:
                # 构建正则: function funcName(...) external/public
                if func_name in ['fallback', 'receive']:
                    # fallback和receive的特殊语法
                    pattern = rf'{func_name}\s*\(\s*\)\s+external'
                else:
                    pattern = rf'function\s+{func_name}\s*\('

                match = re.search(pattern, self.script_content)
                if match:
                    callbacks.append({
                        'name': func_name,
                        'protocol': protocol,
                        'position': match.start()
                    })
                    logger.debug(f"  识别回调函数: {func_name} (协议: {protocol})")

        return callbacks

    # ==========================================================================
    # 阶段2: 函数发现与调用图构建
    # ==========================================================================

    def _find_matching_brace(self, content: str, start: int) -> int:
        """
        找到匹配的右大括号

        正确处理:
        1. 嵌套的 { }
        2. 字符串中的 "{ }"
        3. 注释中的 // { 或 /* { */

        Args:
            content: 完整代码内容
            start: 左括号 { 的位置

        Returns:
            匹配右括号的位置,失败返回-1
        """
        brace_count = 1
        pos = start + 1
        length = len(content)

        # 状态机: code, string_double, string_single, comment_single, comment_multi
        state = 'code'

        while pos < length and brace_count > 0:
            char = content[pos]
            prev_char = content[pos - 1] if pos > 0 else ''
            next_char = content[pos + 1] if pos < length - 1 else ''

            if state == 'code':
                # 进入双引号字符串
                if char == '"' and prev_char != '\\':
                    state = 'string_double'
                # 进入单引号字符串
                elif char == "'" and prev_char != '\\':
                    state = 'string_single'
                # 进入单行注释
                elif char == '/' and next_char == '/':
                    state = 'comment_single'
                    pos += 1  # 跳过第二个/
                # 进入多行注释
                elif char == '/' and next_char == '*':
                    state = 'comment_multi'
                    pos += 1  # 跳过*
                # 计数大括号
                elif char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1

            elif state == 'string_double':
                # 退出双引号字符串
                if char == '"' and prev_char != '\\':
                    state = 'code'

            elif state == 'string_single':
                # 退出单引号字符串
                if char == "'" and prev_char != '\\':
                    state = 'code'

            elif state == 'comment_single':
                # 换行退出单行注释
                if char == '\n':
                    state = 'code'

            elif state == 'comment_multi':
                # */ 退出多行注释
                if char == '*' and next_char == '/':
                    state = 'code'
                    pos += 1  # 跳过/

            pos += 1

        return pos if brace_count == 0 else -1

    def _discover_all_functions(self) -> List[FunctionInfo]:
        """
        扫描脚本发现所有函数定义

        Returns:
            FunctionInfo列表
        """
        if self._functions_cache is not None:
            return self._functions_cache

        # 尝试使用Slither进行精确分析
        if self.use_slither and self.slither_func_analyzer:
            try:
                return self._discover_all_functions_slither()
            except Exception as e:
                logger.warning(f"Slither函数发现失败,回退到正则表达式: {e}")
                # 继续使用正则表达式

        # Fallback: 使用正则表达式
        return self._discover_all_functions_regex()

    def _discover_all_functions_slither(self) -> List[FunctionInfo]:
        """
        使用Slither进行精确的函数发现

        Returns:
            FunctionInfo列表
        """
        logger.debug("  使用Slither进行函数发现...")
        slither_funcs = self.slither_func_analyzer.discover_functions()

        functions = []
        for sf in slither_funcs:
            # 转换Slither的FunctionInfo到本地格式
            # 注意: Slither没有body文本,我们从源码提取
            func_body = ""
            if sf.start_line > 0 and sf.end_line > 0:
                lines = self.script_content.split('\n')
                func_body = '\n'.join(lines[sf.start_line-1:sf.end_line])

            func_info = FunctionInfo(
                name=sf.name,
                visibility=sf.visibility,
                start_pos=0,  # Slither不提供字符位置
                end_pos=0,
                body=func_body
            )
            functions.append(func_info)

        logger.debug(f"  Slither发现 {len(functions)} 个函数: {[f.name for f in functions]}")
        self._functions_cache = functions
        return functions

    def _discover_all_functions_regex(self) -> List[FunctionInfo]:
        """
        使用正则表达式进行函数发现 (原有实现)

        Returns:
            FunctionInfo列表
        """
        functions = []
        content = self.script_content

        # 正则匹配函数头: function name(...) visibility modifiers {
        # 注意: 需要处理 returns(...) 等修饰符
        func_pattern = r'function\s+(\w+)\s*\([^)]*\)\s*(public|external|internal|private)?[^{]*\{'

        for match in re.finditer(func_pattern, content):
            func_name = match.group(1)
            visibility = match.group(2) or 'public'

            # 找到函数体的开始位置 (最后一个{)
            start_pos = match.end() - 1

            # 找到匹配的}
            end_pos = self._find_matching_brace(content, start_pos)

            if end_pos == -1:
                logger.warning(f"无法找到函数 {func_name} 的结束括号,跳过")
                continue

            func_body = content[start_pos:end_pos]

            func_info = FunctionInfo(
                name=func_name,
                visibility=visibility,
                start_pos=start_pos,
                end_pos=end_pos,
                body=func_body
            )

            functions.append(func_info)

        # 特殊处理: fallback和receive函数
        for special_func in ['fallback', 'receive']:
            pattern = rf'{special_func}\s*\(\s*\)\s+external[^{{]*\{{'
            match = re.search(pattern, content)
            if match:
                start_pos = match.end() - 1
                end_pos = self._find_matching_brace(content, start_pos)
                if end_pos != -1:
                    func_body = content[start_pos:end_pos]
                    functions.append(FunctionInfo(
                        name=special_func,
                        visibility='external',
                        start_pos=start_pos,
                        end_pos=end_pos,
                        body=func_body
                    ))

        logger.debug(f"  正则表达式发现 {len(functions)} 个函数: {[f.name for f in functions]}")
        self._functions_cache = functions
        return functions

    def _extract_internal_calls(self, func: FunctionInfo, all_func_names: set) -> List[str]:
        """
        从函数体提取内部函数调用

        Args:
            func: 函数信息
            all_func_names: 所有函数名集合

        Returns:
            内部调用的函数名列表
        """
        internal_calls = []

        # 模式: functionName(...) 但不是 something.functionName(...)
        # 使用负向后查找: 前面不是 . 或其他标识符字符
        pattern = r'(?<![.\w])(\w+)\s*\('

        for match in re.finditer(pattern, func.body):
            func_name = match.group(1)

            # 过滤关键字
            if func_name in self.SOLIDITY_KEYWORDS:
                continue

            # 过滤类型转换
            if func_name in self.SOLIDITY_TYPES:
                continue

            # 只保留在合约中定义的函数
            if func_name in all_func_names:
                internal_calls.append(func_name)

        return list(set(internal_calls))  # 去重

    def _extract_external_calls_from_func(self, func: FunctionInfo) -> List[Dict]:
        """
        从函数体提取外部合约调用

        支持模式:
        1. contractVar.functionName(...)
        2. IInterface(address).functionName(...)
        3. I(address).functionName(...)

        Returns:
            外部调用列表
        """
        external_calls = []

        # 模式1: contractVar.functionName(...)
        pattern1 = r'(\w+)\.(\w+)\s*\('
        for match in re.finditer(pattern1, func.body):
            var_name = match.group(1)
            func_name = match.group(2)

            # 过滤伪外部调用
            if var_name in ['msg', 'tx', 'block', 'abi', 'this', 'super', 'address', 'type']:
                continue

            # 过滤常见视图函数(通常不需要约束)
            if func_name in ['balanceOf', 'allowance', 'totalSupply', 'decimals', 'name', 'symbol']:
                continue

            external_calls.append({
                'type': 'direct',
                'contract_var': var_name,
                'function': func_name,
                'source_function': func.name,
            })

        # 模式2: I(address).functionName(...) 或 IInterface(address).functionName(...)
        pattern2 = r'I(\w*)\(([^)]+)\)\.(\w+)\s*\('
        for match in re.finditer(pattern2, func.body):
            interface_hint = match.group(1) or ''
            address_expr = match.group(2).strip()
            func_name = match.group(3)

            external_calls.append({
                'type': 'interface',
                'interface': f'I{interface_hint}' if interface_hint else 'I',
                'address_expr': address_expr,
                'function': func_name,
                'source_function': func.name,
            })

        return external_calls

    def _build_call_graph(self, functions: List[FunctionInfo]) -> Dict[str, List[str]]:
        """
        构建函数间调用关系图

        Returns:
            {调用者函数名: [被调用者函数名列表]}
        """
        if self._call_graph_cache is not None:
            return self._call_graph_cache

        # 尝试使用Slither进行精确分析
        if self.use_slither and self.slither_callgraph_builder:
            try:
                logger.debug("  使用Slither构建调用图...")
                graph = self.slither_callgraph_builder.build_call_graph()
                self._call_graph_cache = graph
                logger.debug(f"  Slither构建调用图完成: {len(graph)} 个函数")
                return graph
            except Exception as e:
                logger.warning(f"Slither调用图构建失败,回退到正则表达式: {e}")
                # 继续使用正则表达式

        # Fallback: 使用正则表达式
        all_func_names = {f.name for f in functions}
        graph = {}

        for func in functions:
            internal_calls = self._extract_internal_calls(func, all_func_names)
            func.internal_calls = internal_calls  # 缓存到FunctionInfo
            graph[func.name] = internal_calls

        self._call_graph_cache = graph
        logger.debug(f"  正则表达式构建调用图完成: {len(graph)} 个函数")
        return graph

    def _traverse_call_graph_bfs(
        self,
        graph: Dict[str, List[str]],
        entry_points: List[str],
        max_depth: int = 10
    ) -> List[str]:
        """
        从多个入口点BFS遍历调用图

        Args:
            graph: 调用图
            entry_points: 入口点列表
            max_depth: 最大遍历深度(防止无限递归)

        Returns:
            所有可达函数名列表(按访问顺序)
        """
        visited = set()
        reachable = []
        queue = deque()

        # 初始化队列: (函数名, 深度)
        for entry in entry_points:
            if entry in graph:
                queue.append((entry, 0))

        while queue:
            current_func, depth = queue.popleft()

            # 深度限制
            if depth > max_depth:
                logger.warning(f"调用深度超过{max_depth},跳过函数: {current_func}")
                continue

            # 已访问过
            if current_func in visited:
                continue

            visited.add(current_func)
            reachable.append(current_func)

            # 加入被调用的函数
            callees = graph.get(current_func, [])
            for callee in callees:
                if callee not in visited:
                    queue.append((callee, depth + 1))

        return reachable

    def _collect_all_external_calls(self) -> List[Dict]:
        """
        收集所有可达函数的外部调用

        整合调用图遍历和外部调用提取

        Returns:
            去重后的外部调用列表
        """
        # 1. 发现所有函数
        functions = self._discover_all_functions()
        if not functions:
            logger.warning("未发现任何函数定义")
            return []

        # 2. 识别入口点 - 支持多种测试函数命名模式
        entry_points = []

        # 查找所有可能的测试入口函数
        test_patterns = ['testExploit', 'test_poc', 'test_exploit', 'testAttack']
        func_names = {f.name for f in functions}

        for pattern in test_patterns:
            if pattern in func_names:
                entry_points.append(pattern)

        # 如果还没有找到，尝试正则匹配 test* 模式
        if not entry_points:
            for func_name in func_names:
                if func_name.startswith('test') and func_name not in ['setUp']:
                    entry_points.append(func_name)
                    logger.debug(f"  通过模式匹配识别入口点: {func_name}")

        # 如果仍然没有找到，使用默认的 testExploit
        if not entry_points:
            entry_points = ['testExploit']

        # 添加回调函数作为入口点
        callbacks = self._find_callbacks()
        callback_names = [cb['name'] for cb in callbacks]
        entry_points.extend(callback_names)

        logger.info(f"  识别到 {len(entry_points)} 个入口点: {entry_points}")

        # 3. 构建调用图
        call_graph = self._build_call_graph(functions)

        # 4. BFS遍历所有可达函数
        reachable_funcs = self._traverse_call_graph_bfs(call_graph, entry_points)
        logger.info(f"  可达函数: {len(reachable_funcs)}/{len(functions)}")

        # 5. 收集所有可达函数的外部调用
        func_map = {f.name: f for f in functions}
        all_external_calls = []

        for func_name in reachable_funcs:
            if func_name in func_map:
                func = func_map[func_name]
                external_calls = self._extract_external_calls_from_func(func)
                all_external_calls.extend(external_calls)

        # 6. 去重
        unique_calls = self._deduplicate_external_calls(all_external_calls)
        logger.info(f"  收集到 {len(unique_calls)} 个唯一外部调用")

        return unique_calls

    def _deduplicate_external_calls(self, calls: List[Dict]) -> List[Dict]:
        """去除重复的外部调用"""
        seen = set()
        unique = []

        for call in calls:
            # 用 (合约标识, 函数名) 作为唯一性key
            contract_id = call.get('contract_var') or call.get('address_expr', '')
            key = (contract_id, call['function'])

            if key not in seen:
                seen.add(key)
                unique.append(call)

        return unique

    def _resolve_address_from_var(self, var_name: str) -> Optional[str]:
        """
        从变量声明中解析合约地址

        支持模式:
        - address constant varName = 0x...;
        - address varName = 0x...;
        - IContract varName = IContract(0x...);

        Args:
            var_name: 变量名

        Returns:
            地址字符串(小写),未找到返回None
        """
        patterns = [
            # address constant/immutable varName = 0x...
            rf'address\s+(?:constant|immutable)?\s*{var_name}\s*=\s*(0x[a-fA-F0-9]{{40}})',
            # IContract varName = IContract(0x...)
            rf'\w+\s+{var_name}\s*=\s*\w+\s*\(\s*(?:payable\s*\()?\s*(0x[a-fA-F0-9]{{40}})',
            # 直接赋值 varName = 0x...
            rf'{var_name}\s*=\s*(0x[a-fA-F0-9]{{40}})',
        ]

        for pattern in patterns:
            match = re.search(pattern, self.script_content, re.IGNORECASE)
            if match:
                return match.group(1).lower()

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

        # V3增强: 初始化符号执行求值器
        if V3_AVAILABLE and hasattr(state_analyzer, 'layout_inferrer') and state_analyzer.layout_inferrer:
            try:
                # SymbolicParameterEvaluator需要AST分析器和状态分析器
                # 但我们在V2.5中没有AST,所以传入None,仅使用状态读取功能
                self.param_evaluator = SymbolicParameterEvaluator(None, state_analyzer)
                logger.info("V3 SymbolicParameterEvaluator已初始化(无AST模式)")
            except Exception as e:
                logger.warning(f"V3 SymbolicParameterEvaluator初始化失败: {e}, 回退到V2")
                self.param_evaluator = None
        else:
            self.param_evaluator = None
            if not V3_AVAILABLE:
                logger.debug("V3不可用,跳过SymbolicParameterEvaluator初始化")

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

    def generate(self, attack_info: Dict, vuln_address: str, firewall_config=None) -> List[Dict]:
        """
        生成约束规则

        核心改进:
        1. 分析状态差异找到真正变化的slot
        2. 关联参数与slot变化
        3. 推断合理的阈值
        4. 如果有防火墙配置，只分析被保护的函数

        Args:
            attack_info: 攻击信息
            vuln_address: 被攻击合约地址
            firewall_config: 防火墙配置（可选）
        """
        constraints = []

        # 0. 过滤被保护的函数（如果有防火墙配置）
        attack_calls = attack_info.get('attack_calls', [])
        if firewall_config:
            protected_functions = firewall_config.get_function_names()
            if protected_functions:
                attack_calls = [
                    call for call in attack_calls
                    if call.get('function') in protected_functions
                ]
                logger.info(f"  根据防火墙配置，分析 {len(attack_calls)}/{len(attack_info.get('attack_calls', []))} 个被保护函数")

        if not attack_calls:
            logger.warning("  没有要分析的函数调用")
            return constraints

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
        for call in attack_calls:
            func_name = call['function']
            params = call['parameters']

            # 识别攻击模式 - 使用行为分析
            pattern = self._identify_attack_pattern(func_name, slot_changes, loop_info)
            if not pattern or pattern == 'unknown':
                continue

            # 找到动态参数（扩展支持数组/地址/字节等）
            dynamic_params = [
                p for p in params
                if p['is_dynamic'] and p['type'] in (
                    'uint256', 'int256', 'uint8', 'address', 'bool', 'bytes', 'bytes32',
                    'address[]', 'uint256[]', 'uint8[]', 'bytes[]'
                )
            ]

            for param in dynamic_params:
                p_type = param['type']

                # ====== 数值标量 ======
                if p_type in ('uint256', 'int256', 'uint8'):
                    param_value = self._estimate_param_value(param['value_expr'], vuln_address)
                    if param_value is None or param_value == 0:
                        continue

                    correlations = self.correlator.correlate(param_value, slot_changes)

                    if correlations:
                        best_corr = correlations[0]
                        slot_change = best_corr['slot_change']
                        state_value = slot_change['after'] if slot_change.get('is_new_slot', False) else slot_change['before']
                        threshold_info = self.threshold_inferrer.infer_threshold(param_value, state_value, pattern)
                        semantic = self.state_analyzer.infer_slot_semantic(
                            best_corr['slot'], slot_change,
                            attack_info.get('vulnerable_contract', {}).get('name') or 'Unknown'
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
                    elif slot_changes:
                        top_change = slot_changes[0]
                        state_value = top_change['after'] if top_change.get('is_new_slot', False) else top_change['before']
                        threshold_info = self.threshold_inferrer.infer_threshold(param_value, state_value, pattern)
                        semantic = self.state_analyzer.infer_slot_semantic(
                            top_change['slot'], top_change,
                            attack_info.get('vulnerable_contract', {}).get('name') or 'Unknown'
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

                # ====== 地址（标量/数组） ======
                elif p_type in ('address', 'address[]'):
                    addr_values = self._normalize_address_values(param, vuln_address)
                    if not addr_values:
                        continue
                    constraint = {
                        "function": func_name,
                        "signature": call.get("signature"),
                        "attack_pattern": pattern,
                        "constraint": {
                            "type": "discrete_addresses",
                            "expression": f"{param.get('name') or param['index']} in observed_addresses",
                            "semantics": "Restrict addresses to observed attack set",
                            "attack_values": addr_values,
                            "variables": {
                                "addresses": {
                                    "source": "function_parameter",
                                    "index": param['index'],
                                    "type": p_type,
                                    "value_expr": param.get('value_expr')
                                }
                            }
                        },
                        "analysis": {
                            "state_value": None,
                            "threshold": None,
                            "coefficient": None,
                            "attack_intensity": None,
                            "reasoning": "Address whitelist derived from attack script",
                            "correlation_type": "discrete",
                            "correlation_confidence": 0.3
                        }
                    }
                    constraints.append(constraint)

                # ====== 布尔 ======
                elif p_type == 'bool':
                    constraint = {
                        "function": func_name,
                        "signature": call.get("signature"),
                        "attack_pattern": pattern,
                        "constraint": {
                            "type": "discrete_bool",
                            "expression": f"{param.get('name') or param['index']} in [true,false]",
                            "semantics": "Boolean flag must be explicit",
                            "attack_values": [True, False],
                            "variables": {
                                "flag": {
                                    "source": "function_parameter",
                                    "index": param['index'],
                                    "type": "bool",
                                    "value_expr": param.get('value_expr')
                                }
                            }
                        },
                        "analysis": {
                            "state_value": None,
                            "threshold": None,
                            "coefficient": None,
                            "attack_intensity": None,
                            "reasoning": "Boolean parameter limited to true/false",
                            "correlation_type": "discrete",
                            "correlation_confidence": 0.2
                        }
                    }
                    constraints.append(constraint)

                # ====== 字节（含 bytes[]） ======
                elif p_type in ('bytes', 'bytes32', 'bytes[]'):
                    byte_info = self._normalize_bytes_values(param)
                    if not byte_info:
                        continue
                    constraint = {
                        "function": func_name,
                        "signature": call.get("signature"),
                        "attack_pattern": pattern,
                        "constraint": {
                            "type": "bytes_pattern",
                            "expression": f"{param.get('name') or param['index']} length in [{byte_info['min_len']},{byte_info['max_len']}]",
                            "semantics": "Restrict bytes payload length",
                            "attack_values": byte_info['samples'],
                            "variables": {
                                "bytes": {
                                    "source": "function_parameter",
                                    "index": param['index'],
                                    "type": p_type,
                                    "value_expr": param.get('value_expr')
                                }
                            },
                            "range": {
                                "min_len": byte_info['min_len'],
                                "max_len": byte_info['max_len']
                            }
                        },
                        "analysis": {
                            "state_value": None,
                            "threshold": None,
                            "coefficient": None,
                            "attack_intensity": None,
                            "reasoning": "Bytes payload constrained by observed length",
                            "correlation_type": "discrete",
                            "correlation_confidence": 0.2
                        }
                    }
                    constraints.append(constraint)

                # ====== 数组数值 ======
                elif p_type in ('uint256[]', 'uint8[]'):
                    numeric_info = self._normalize_numeric_array(param)
                    if not numeric_info:
                        continue
                    constraint = {
                        "function": func_name,
                        "signature": call.get("signature"),
                        "attack_pattern": pattern,
                        "constraint": {
                            "type": "capped_array",
                            "expression": f"{param.get('name') or param['index']} elements in [{numeric_info['min']},{numeric_info['max']}]",
                            "semantics": "Restrict numeric array elements to observed range",
                            "attack_values": numeric_info['values'],
                            "range": {
                                "min": numeric_info['min'],
                                "max": numeric_info['max']
                            },
                            "variables": {
                                "values": {
                                    "source": "function_parameter",
                                    "index": param['index'],
                                    "type": p_type,
                                    "value_expr": param.get('value_expr')
                                }
                            },
                            "len_range": numeric_info.get('len_range')
                        },
                        "analysis": {
                            "state_value": None,
                            "threshold": None,
                            "coefficient": None,
                            "attack_intensity": None,
                            "reasoning": "Numeric array bounded by observed values",
                            "correlation_type": "discrete",
                            "correlation_confidence": 0.3
                        }
                    }
                    constraints.append(constraint)

        return constraints

    def _estimate_param_value(self, value_expr: str, vuln_address: str) -> Optional[int]:
        """
        估算参数值 - V3增强:使用ContractProxy精确读取

        支持的格式:
        - BARL.balanceOf(address(wBARL))
        - 数字字面量
        - 变量名
        """
        value_expr = value_expr.strip()

        # 1. 数字字面量
        if value_expr.isdigit():
            return int(value_expr)

        # V3增强: 尝试使用ContractProxy精确求值balanceOf表达式
        if V3_AVAILABLE and self.param_evaluator:
            pattern = r'(\w+)\.balanceOf\(address\((\w+)\)\)'
            match = re.search(pattern, value_expr)
            if match:
                token_name = match.group(1)
                holder_name = match.group(2)

                try:
                    # 从addresses_info查找地址
                    token_addr = None
                    holder_addr = None

                    if self.state_analyzer.addresses_info:
                        for addr, info in self.state_analyzer.addresses_info.items():
                            name = info.get('name', '')
                            if name == token_name or token_name in name:
                                token_addr = addr
                            if name == holder_name or holder_name in name:
                                holder_addr = addr

                    if token_addr and holder_addr:
                        # 使用V3 ContractProxy读取余额
                        token_proxy = ContractProxy(token_addr, self.state_analyzer)
                        balance = token_proxy.call('balanceOf', holder_addr)

                        if balance > 0:
                            logger.info(f"V3精确求值: {value_expr} = {balance:,}")
                            return balance
                        else:
                            logger.debug(f"V3求值返回0,回退到V2估算")
                except Exception as e:
                    logger.debug(f"V3求值失败: {e}, 回退到V2")

        # 2. balanceOf表达式 (V2回退逻辑)
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

    def _normalize_address_values(self, param: Dict, vuln_address: Optional[str] = None) -> List[str]:
        """解析地址或地址数组参数，返回小写十六进制字符串列表"""
        value_expr = param.get('value_expr', '') or ''
        addrs = set()
        for match in re.findall(r'0x[a-fA-F0-9]{40}', value_expr):
            addrs.add(match.lower())
        # 解析 value_expr 中的 address(NAME) 模式
        for inner in re.findall(r'address\(([^)]+)\)', value_expr):
            if inner.startswith('0x') and len(inner) == 42:
                addrs.add(inner.lower())
            else:
                resolved = self._resolve_var_address(inner)
                if resolved:
                    addrs.add(resolved.lower())
        # 尝试从 seeds 中提取
        for seed in param.get('seeds', []):
            for match in re.findall(r'0x[a-fA-F0-9]{40}', seed):
                addrs.add(match.lower())
            if 'address(' in seed:
                inner = re.findall(r'address\(([^)]+)\)', seed)
                for item in inner:
                    if item.startswith('0x') and len(item) == 42:
                        addrs.add(item.lower())
                    else:
                        resolved = self._resolve_var_address(item)
                        if resolved:
                            addrs.add(resolved.lower())
            else:
                # 变量名直接解析
                resolved = self._resolve_var_address(seed)
                if resolved:
                    addrs.add(resolved.lower())
        # 特殊处理 address(this)
        if 'address(this' in value_expr.replace(" ", "").lower() and vuln_address:
            addrs.add(vuln_address.lower())
        if not addrs and param['type'] == 'address[]':
            # 回退默认值，避免空数组
            addrs.update({
                '0x0000000000000000000000000000000000000000',
                '0xffffffffffffffffffffffffffffffffffffffff'
            })
        if param['type'] == 'address' and not addrs and value_expr:
            return []
        return list(addrs)

    def _resolve_var_address(self, name: str) -> Optional[str]:
        """根据变量名从addresses_info解析出地址"""
        if not name or not self.state_analyzer or not self.state_analyzer.addresses_info:
            return None
        clean = name.strip()
        info_obj = self.state_analyzer.addresses_info
        try:
            items = info_obj.items()
        except Exception:
            # addresses_info 可能是列表
            items = []
            if isinstance(info_obj, list):
                for entry in info_obj:
                    addr = entry.get('address')
                    if not addr:
                        continue
                    name_field = entry.get('name', '')
                    aliases = entry.get('aliases', []) or []
                    items.append((addr, {'name': name_field, 'aliases': aliases}))

        for addr, info in items:
            if info.get('name') == clean or clean in (info.get('aliases') or []):
                return addr
        return None

    def _normalize_numeric_array(self, param: Dict) -> Optional[Dict]:
        """解析数值数组，返回元素列表及范围"""
        value_expr = param.get('value_expr', '') or ''
        nums = []
        for match in re.findall(r'\d+', value_expr):
            try:
                nums.append(int(match))
            except Exception:
                continue
        # seeds 提取
        for seed in param.get('seeds', []):
            for match in re.findall(r'\d+', seed):
                try:
                    nums.append(int(match))
                except Exception:
                    continue
        if not nums:
            # 如果表达式中没有数字，提供保守回退，避免空集合
            if param['type'] == 'uint8[]':
                nums = [0, 1]
            else:
                return None
        return {
            "values": nums,
            "min": min(nums),
            "max": max(nums),
            "len_range": {"min": len(nums), "max": len(nums)}
        }

    def _normalize_bytes_values(self, param: Dict) -> Optional[Dict]:
        """解析字节参数，提取长度和样本"""
        value_expr = param.get('value_expr', '') or ''
        samples = []
        lengths = []
        hex_matches = re.findall(r'0x[a-fA-F0-9]+', value_expr)
        if hex_matches:
            for m in hex_matches[:5]:
                samples.append(m)
                lengths.append((len(m) - 2) // 2)
        elif value_expr:
            samples.append(value_expr[:100])
            lengths.append(len(value_expr))

        if not samples:
            return None

        return {
            "samples": samples,
            "min_len": min(lengths),
            "max_len": max(lengths)
        }

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

            dynamic_params = [
                p for p in params
                if p['is_dynamic'] and p['type'] in (
                    'uint256', 'int256', 'uint8', 'address', 'bool', 'bytes', 'bytes32',
                    'address[]', 'uint256[]', 'uint8[]', 'bytes[]'
                )
            ]

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

    def __init__(self, repo_root: Path, use_firewall_config: bool = False, use_slither: bool = True):
        self.repo_root = repo_root
        self.extracted_dir = repo_root / "extracted_contracts"
        self.scripts_dir = repo_root / "src" / "test"
        self.use_firewall_config = use_firewall_config
        self.use_slither = use_slither

        # 初始化防火墙配置读取器
        if self.use_firewall_config:
            try:
                from firewall_config_reader import FirewallConfigReader
                self.firewall_reader = FirewallConfigReader(repo_root)
                logger.info("防火墙配置读取器已初始化")
            except ImportError as e:
                logger.warning(f"无法加载防火墙配置读取器: {e}")
                self.firewall_reader = None
        else:
            self.firewall_reader = None

    def extract_single(self, protocol_name: str, year_month: str) -> Optional[Dict]:
        """提取单个协议的约束"""
        logger.timer_start(f"提取协议: {protocol_name}")
        logger.info(f"开始提取约束 (V2): {protocol_name}")

        # 加载防火墙配置（如果启用）
        firewall_config = None
        if self.use_firewall_config and self.firewall_reader:
            logger.timer_start(f"{protocol_name} - 加载防火墙配置")
            firewall_config = self.firewall_reader.load_config(protocol_name, year_month)
            logger.timer_end(f"{protocol_name} - 加载防火墙配置")

        # 定位文件
        protocol_dir = self.extracted_dir / year_month / protocol_name
        script_path = self.scripts_dir / year_month / f"{protocol_name}.sol"

        if not script_path.exists():
            logger.warning(f"攻击脚本不存在: {script_path}")
            logger.timer_end(f"提取协议: {protocol_name}")
            return None

        if not protocol_dir.exists():
            logger.warning(f"协议目录不存在: {protocol_dir}")
            logger.timer_end(f"提取协议: {protocol_name}")
            return None

        # 解析攻击脚本
        logger.timer_start(f"{protocol_name} - 解析攻击脚本")
        parser = AttackScriptParser(script_path, use_slither=self.use_slither)
        attack_info = parser.parse()
        logger.timer_end(f"{protocol_name} - 解析攻击脚本")

        vulnerable_contract = attack_info.get('vulnerable_contract', {})
        vuln_address = vulnerable_contract.get('address')

        logger.info(f"  被攻击合约: {vulnerable_contract.get('name')} ({vuln_address})")
        logger.info(f"  识别到 {len(attack_info.get('attack_calls', []))} 个函数调用")

        # 状态差异分析（传入防火墙配置）
        logger.timer_start(f"{protocol_name} - 状态差异分析")
        state_analyzer = StateDiffAnalyzer(protocol_dir, firewall_config)
        logger.timer_end(f"{protocol_name} - 状态差异分析初始化")

        # 获取分析目标（如果有防火墙配置，会使用其中的合约地址）
        logger.timer_start(f"{protocol_name} - 获取分析目标")
        analysis_targets = state_analyzer.get_analysis_targets()
        logger.timer_end(f"{protocol_name} - 获取分析目标")

        # 分析所有目标合约的状态变化
        logger.timer_start(f"{protocol_name} - 分析状态变化")
        all_slot_changes = {}
        for target_addr in analysis_targets:
            slot_changes = state_analyzer.analyze_slot_changes(target_addr)
            if slot_changes:
                all_slot_changes[target_addr] = slot_changes
                logger.info(f"  {target_addr[:12]}...: {len(slot_changes)} 个slot变化")
        logger.timer_end(f"{protocol_name} - 分析状态变化")

        # 如果没有任何状态变化，记录警告
        if not all_slot_changes:
            logger.warning("  所有分析目标都没有状态变化")

        # 生成约束（传入防火墙配置）
        logger.timer_start(f"{protocol_name} - 生成约束")
        constraint_gen = ConstraintGeneratorV2(state_analyzer)

        # 确定要使用的主要分析地址
        primary_address = None

        # 优先使用有状态变化的合约
        if all_slot_changes:
            # 选择变化最大的合约作为主要分析目标
            primary_address = max(all_slot_changes.keys(), key=lambda k: len(all_slot_changes[k]))
            logger.info(f"  使用变化最大的合约作为主要分析目标: {primary_address[:12]}... ({len(all_slot_changes[primary_address])} slots)")
        elif vuln_address:
            # 如果没有状态变化，使用原始被攻击合约
            primary_address = vuln_address
            logger.info(f"  使用原始被攻击合约: {primary_address[:12]}...")

        if primary_address:
            constraints = constraint_gen.generate(attack_info, primary_address, firewall_config)
        else:
            constraints = constraint_gen._generate_heuristic_constraints(attack_info)

        logger.timer_end(f"{protocol_name} - 生成约束")
        logger.success(f"  生成约束: {len(constraints)} 个")

        # 构建结果
        loop_info = attack_info.get('loop_info') or {}

        # 获取主要分析地址的slot变化（用于构建结果）
        primary_slot_changes = []
        if primary_address and primary_address in all_slot_changes:
            primary_slot_changes = all_slot_changes[primary_address]

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
                    for c in primary_slot_changes[:5]  # 只保留前5个
                ],
                "total_changed_slots": len(primary_slot_changes)
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

        logger.timer_end(f"提取协议: {protocol_name}")
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
        logger.timer_start("批量提取")
        results = {}
        processed_count = 0
        success_count = 0
        error_count = 0

        year_month_dirs = []
        if year_month_filter:
            filter_dir = self.extracted_dir / year_month_filter
            if filter_dir.exists():
                year_month_dirs = [filter_dir]
        else:
            year_month_dirs = [d for d in self.extracted_dir.iterdir() if d.is_dir()]

        # 统计总数
        total_protocols = 0
        for year_month_dir in year_month_dirs:
            total_protocols += sum(1 for p in year_month_dir.iterdir() if p.is_dir())

        logger.info(f"准备处理 {total_protocols} 个协议...")

        for year_month_dir in year_month_dirs:
            year_month = year_month_dir.name

            for protocol_dir in sorted(year_month_dir.iterdir()):
                if not protocol_dir.is_dir():
                    continue

                protocol_name = protocol_dir.name
                processed_count += 1

                logger.info(f"\n{'='*60}")
                logger.info(f"进度: {processed_count}/{total_protocols} - {protocol_name}")
                logger.info(f"{'='*60}")

                try:
                    result = self.extract_single(protocol_name, year_month)
                    if result is not None:
                        self.save_result(result, protocol_name, year_month)
                        results[protocol_name] = result
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    logger.error(f"处理 {protocol_name} 时出错: {e}")
                    import traceback
                    traceback.print_exc()
                    error_count += 1

        logger.timer_end("批量提取")
        logger.info(f"\n{'='*60}")
        logger.success(f"批量提取完成!")
        logger.success(f"总计: {processed_count} 个协议")
        logger.success(f"成功: {success_count} 个")
        logger.error(f"失败: {error_count} 个")
        logger.info(f"{'='*60}")

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
    parser.add_argument('--use-firewall-config', action='store_true',
                       help='使用防火墙配置确定分析目标（从constraint_rules_v2.json读取）')
    parser.add_argument('--use-slither', dest='use_slither', action='store_true', default=True,
                       help='使用Slither进行精确AST分析 (默认启用)')
    parser.add_argument('--no-slither', dest='use_slither', action='store_false',
                       help='禁用Slither,使用正则表达式分析')
    parser.add_argument('--log-file', help='日志文件路径 (默认: logs/extract_constraints_YYYYMMDD_HHMMSS.log)')

    args = parser.parse_args()

    # 配置日志文件
    if args.log_file:
        log_file = Path(args.log_file)
    else:
        # 默认日志文件路径，使用时间戳
        log_dir = Path(__file__).parent / "logs"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"extract_constraints_{timestamp}.log"

    # 重新初始化全局logger以支持文件输出
    global logger
    logger = Logger(log_file=str(log_file))
    logger.info(f"日志文件: {log_file}")
    logger.info(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)

    repo_root = Path(__file__).parent
    extractor = ConstraintExtractorV2(
        repo_root,
        use_firewall_config=args.use_firewall_config,
        use_slither=args.use_slither
    )

    # 显示使用的分析方法
    if args.use_slither and SLITHER_AVAILABLE:
        logger.info("✓ 分析模式: Slither精确AST解析")
    else:
        logger.info("分析模式: 正则表达式(fallback)")

    # 记录开始时间
    start_time = time.time()

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

    # 记录总耗时
    total_time = time.time() - start_time
    logger.info("="*60)
    logger.success(f"总耗时: {logger._format_time(total_time)}")
    logger.info(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)
    logger.success(f"日志已保存到: {log_file}")


if __name__ == "__main__":
    main()
