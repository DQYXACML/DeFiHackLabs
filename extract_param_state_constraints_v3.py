#!/usr/bin/env python3
"""
参数-状态约束提取器 V3 (Parameter-State Constraint Extractor V3)

V3核心改进:
1. 使用Solidity AST替代正则表达式解析攻击脚本
2. 基于状态变化的动态Storage布局推断
3. 符号执行增强的参数值精确求值

作者: FirewallOnchain Team
版本: 3.0.0
日期: 2025-01-21
"""

import argparse
import json
import re
import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set
from decimal import Decimal, getcontext
from collections import defaultdict
from dataclasses import dataclass, field
from eth_utils import keccak

# 设置高精度
getcontext().prec = 78

# =============================================================================
# 日志工具
# =============================================================================

class Logger:
    """彩色日志器"""
    COLORS = {
        'info': '\033[0;34m',
        'success': '\033[0;32m',
        'warning': '\033[1;33m',
        'error': '\033[0;31m',
        'debug': '\033[0;36m',
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

    @staticmethod
    def debug(msg):
        print(f"{Logger.COLORS['debug']}[DEBUG]{Logger.COLORS['reset']} {msg}")

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


def compute_mapping_slot(key: str, base_slot: int) -> str:
    """
    计算Solidity mapping的storage slot

    Formula: keccak256(abi.encodePacked(key, base_slot))
    """
    # 地址需要左填充到32字节
    key_bytes = bytes.fromhex(key.replace('0x', '').zfill(64))
    base_bytes = base_slot.to_bytes(32, 'big')

    slot_hash = keccak(key_bytes + base_bytes)
    return '0x' + slot_hash.hex()


# =============================================================================
# 数据结构定义
# =============================================================================

@dataclass
class ParamInfo:
    """参数信息"""
    ast_node: Dict
    type: str
    is_literal: bool
    literal_value: Optional[Any]
    expression: str
    dependencies: List[str] = field(default_factory=list)
    index: int = 0


@dataclass
class LoopInfo:
    """循环信息"""
    count: Optional[int]
    type: str  # 'for', 'while', 'do-while'
    ast_node: Optional[Dict] = None


@dataclass
class CallInfo:
    """函数调用信息"""
    contract_address: str
    function_name: str
    parameters: List[ParamInfo]
    line_number: int
    ast_node: Dict
    loop_context: Optional[LoopInfo] = None


@dataclass
class ContractInfo:
    """合约信息"""
    address: str
    name: str
    call_count: int
    functions: List[str]
    score: float


@dataclass
class AddressDeclaration:
    """地址声明信息"""
    variable_name: str  # 变量名(如 "wBARL")
    interface_name: Optional[str]  # 接口类型名(如 "IwBARL")
    address: str  # 地址值
    is_constant: bool  # 是否为constant
    is_immutable: bool  # 是否为immutable
    visibility: str  # 可见性: "public", "private", "internal", "external"
    line_number: int  # 源码行号


@dataclass
class VariableInfo:
    """Storage变量信息"""
    slot: str
    name: str
    type: str
    confidence: float


@dataclass
class MappingInfo:
    """Mapping信息"""
    base_slot: int
    name: str
    key_type: str
    value_type: str
    known_keys: List[str]


@dataclass
class StorageLayout:
    """Storage布局"""
    contract_address: str
    variables: Dict[str, VariableInfo] = field(default_factory=dict)
    mappings: Dict[str, MappingInfo] = field(default_factory=dict)

    def add_variable(self, slot: str, name: str, type: str, confidence: float):
        self.variables[slot] = VariableInfo(
            slot=slot, name=name, type=type, confidence=confidence
        )

    def add_mapping(self, base_slot: int, name: str, key_type: str, value_type: str, known_keys: List[str]):
        self.mappings[str(base_slot)] = MappingInfo(
            base_slot=base_slot, name=name,
            key_type=key_type, value_type=value_type,
            known_keys=known_keys
        )

    def get_semantic(self, slot: str) -> Optional[str]:
        """获取slot的语义名称"""
        if slot in self.variables:
            return self.variables[slot].name

        # 检查是否为mapping的派生slot
        for mapping in self.mappings.values():
            if self._is_derived_from_mapping(slot, mapping):
                key = self._extract_key_from_slot(slot, mapping)
                if key:
                    return f"{mapping.name}[{key}]"

        return None

    def _is_derived_from_mapping(self, slot: str, mapping: MappingInfo) -> bool:
        """检查slot是否由mapping派生"""
        # 简化检查：看slot是否在known_keys中
        for key in mapping.known_keys:
            computed_slot = compute_mapping_slot(key, mapping.base_slot)
            if computed_slot.lower() == slot.lower():
                return True
        return False

    def _extract_key_from_slot(self, slot: str, mapping: MappingInfo) -> Optional[str]:
        """从slot反推key"""
        for key in mapping.known_keys:
            computed_slot = compute_mapping_slot(key, mapping.base_slot)
            if computed_slot.lower() == slot.lower():
                return key
        return None


class CallGraph:
    """调用图"""
    def __init__(self):
        self.external_calls: Dict[str, List[CallInfo]] = defaultdict(list)
        self.internal_calls: Dict[str, List[str]] = defaultdict(list)

    def add_call(self, call: CallInfo):
        if call.contract_address:
            self.external_calls[call.contract_address].append(call)


# =============================================================================
# 改进1: AST-Based Attack Script Parser
# =============================================================================

class SolidityASTAnalyzer:
    """基于Solidity编译器AST的静态分析器"""

    def __init__(self, script_path: Path, repo_root: Path):
        self.script_path = script_path
        self.repo_root = repo_root
        self.ast = None
        self.call_graph = None
        self.node_parents: Dict[int, Dict] = {}  # 维护父节点引用
        self.source_lines: List[str] = []

        try:
            self.ast = self._get_ast()
            self.source_lines = script_path.read_text().split('\n')
            self._build_parent_references()
            self.call_graph = self._build_call_graph()
        except Exception as e:
            logger.warning(f"AST获取失败: {e}")
            raise

    def _get_ast(self) -> Dict:
        """获取AST - 优先从forge build产物，fallback到solc"""
        # 方法1: 从Foundry metadata读取 (最可靠)
        contract_name = self.script_path.stem

        # Foundry会为每个合约文件生成多个artifacts
        # 我们需要找到主测试合约的artifact
        out_dir = self.repo_root / "out" / f"{contract_name}.sol"

        if out_dir.exists():
            logger.debug(f"从Foundry artifacts读取AST: {out_dir}")

            # 查找所有JSON artifacts
            for artifact_file in out_dir.glob("*.json"):
                try:
                    with open(artifact_file, 'r') as f:
                        artifact = json.load(f)

                    # 检查metadata中的AST
                    metadata_str = artifact.get('metadata')
                    if metadata_str:
                        metadata = json.loads(metadata_str)
                        # Solidity编译器的metadata包含完整源码和AST
                        sources = metadata.get('sources', {})
                        for source_path, source_data in sources.items():
                            if contract_name in source_path:
                                # 找到了！但metadata只有源码，没有AST
                                # 需要从rawMetadata或其他字段获取
                                pass

                    # 尝试从rawMetadata获取
                    raw_metadata = artifact.get('rawMetadata')
                    if raw_metadata:
                        raw_data = json.loads(raw_metadata)
                        sources = raw_data.get('sources', {})
                        for source_path, source_data in sources.items():
                            # AST在sources的ast字段
                            if 'ast' in source_data and contract_name in source_path:
                                logger.success(f"从{artifact_file.name}读取AST成功")
                                return source_data['ast']

                except Exception as e:
                    logger.debug(f"解析{artifact_file.name}失败: {e}")
                    continue

        # 方法2: 强制重新编译获取AST
        logger.info(f"未找到AST artifacts，使用forge build重新编译...")

        # 使用forge来编译，这样会自动处理所有依赖
        compile_cmd = ['forge', 'build', '--ast', '--force']

        logger.debug(f"执行命令: {' '.join(compile_cmd)}")

        result = subprocess.run(
            compile_cmd,
            capture_output=True,
            text=True,
            cwd=self.repo_root,
            timeout=120
        )

        if result.returncode != 0:
            logger.warning(f"forge build失败: {result.stderr}")
        else:
            logger.info("forge build成功，重新尝试从artifacts读取...")
            # 递归调用自己（只递归一次）
            if not hasattr(self, '_retry_count'):
                self._retry_count = 1
                return self._get_ast()

        # 方法3: 使用solc编译（带remappings）
        logger.debug(f"使用solc编译获取AST")

        # 读取remappings.txt
        remappings = []
        remappings_file = self.repo_root / "remappings.txt"
        if remappings_file.exists():
            with open(remappings_file, 'r') as f:
                remappings = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        # 查找solc
        solc_paths = ['/usr/bin/solc', 'solc']

        solc_cmd = None
        for solc_path in solc_paths:
            try:
                result = subprocess.run([solc_path, '--version'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    version_output = result.stdout
                    if '0.8.' in version_output or '0.9.' in version_output:
                        solc_cmd = solc_path
                        version_line = [line for line in version_output.split('\n') if 'Version:' in line]
                        version_str = version_line[0] if version_line else version_output.split('\n')[0]
                        logger.debug(f"使用solc: {solc_path} ({version_str.strip()})")
                        break
            except Exception as e:
                logger.debug(f"检查{solc_path}失败: {e}")
                continue

        if not solc_cmd:
            raise RuntimeError("solc >= 0.8.0 not found. Please install solidity compiler")

        # 构建solc命令（带remappings）
        cmd = [solc_cmd, '--ast-compact-json', '--base-path', str(self.repo_root)]

        # 添加remappings
        for remap in remappings:
            cmd.extend(['--' + remap.replace('=', ' ')])

        # 添加include paths
        cmd.extend(['--include-path', str(self.repo_root / 'lib')])
        cmd.append(str(self.script_path))

        logger.debug(f"执行命令: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.repo_root, timeout=60)

        if result.returncode != 0:
            # 最后尝试：简化命令
            cmd_simple = [solc_cmd, '--ast-compact-json', str(self.script_path)]
            result = subprocess.run(cmd_simple, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                raise RuntimeError(f"solc compilation failed: {result.stderr}")

        # 解析输出
        output = result.stdout
        json_start = output.find('{')
        if json_start == -1:
            raise RuntimeError("No JSON found in solc output")

        json_str = output[json_start:]
        return json.loads(json_str)

    def _build_parent_references(self):
        """构建AST节点的父节点引用"""
        def walk(node: Dict, parent: Optional[Dict] = None):
            if not isinstance(node, dict):
                return

            node_id = node.get('id')
            if node_id is not None and parent is not None:
                self.node_parents[node_id] = parent

            # 递归遍历子节点
            for key, value in node.items():
                if isinstance(value, dict):
                    walk(value, node)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            walk(item, node)

        walk(self.ast)

    def _build_call_graph(self) -> CallGraph:
        """构建函数调用图"""
        graph = CallGraph()

        # 遍历AST找到所有外部调用
        for node in self._walk_ast(self.ast):
            if node.get('nodeType') == 'FunctionCall':
                self._analyze_function_call(node, graph)

        return graph

    def _walk_ast(self, node: Any) -> List[Dict]:
        """遍历AST节点"""
        nodes = []

        if isinstance(node, dict):
            nodes.append(node)
            for value in node.values():
                nodes.extend(self._walk_ast(value))
        elif isinstance(node, list):
            for item in node:
                nodes.extend(self._walk_ast(item))

        return nodes

    def _analyze_function_call(self, node: Dict, graph: CallGraph):
        """分析单个函数调用节点"""
        expression = node.get('expression', {})

        if expression.get('nodeType') == 'MemberAccess':
            # 形如: wBARL.flash(...)
            base = expression.get('expression', {})
            member_name = expression.get('memberName', '')

            # 获取合约地址
            contract_addr = self._resolve_address(base)

            if not contract_addr:
                return

            # 提取参数
            arguments = node.get('arguments', [])
            params = []
            for idx, arg in enumerate(arguments):
                param_info = self._extract_param_info(arg)
                param_info.index = idx
                params.append(param_info)

            # 获取源码位置
            src_info = node.get('src', '').split(':')
            line_number = self._offset_to_line(int(src_info[0])) if src_info and src_info[0].isdigit() else 0

            # 检查是否在循环中
            loop_context = self._find_loop_context(node)

            graph.add_call(CallInfo(
                contract_address=contract_addr,
                function_name=member_name,
                parameters=params,
                line_number=line_number,
                ast_node=node,
                loop_context=loop_context
            ))

    def _resolve_address(self, node: Dict) -> Optional[str]:
        """解析表达式中的地址"""
        if node.get('nodeType') == 'Identifier':
            var_name = node.get('name', '')
            return self._find_variable_value(var_name)

        elif node.get('nodeType') == 'FunctionCall':
            # 处理类型转换: IwBARL(0x123...)
            func_expr = node.get('expression', {})
            if func_expr.get('nodeType') == 'Identifier':
                args = node.get('arguments', [])
                if args:
                    first_arg = args[0]
                    if first_arg.get('nodeType') == 'Literal':
                        value = first_arg.get('value', '')
                        # 清理引号
                        value = value.strip('"').strip("'")
                        if value.startswith('0x') and len(value) == 42:
                            return value.lower()
                    elif first_arg.get('nodeType') == 'FunctionCall':
                        # 嵌套调用如 address(0x...)
                        return self._resolve_address(first_arg)

        return None

    def _find_variable_value(self, var_name: str) -> Optional[str]:
        """查找变量的实际值"""
        for node in self._walk_ast(self.ast):
            if node.get('nodeType') == 'VariableDeclaration':
                if node.get('name') == var_name:
                    value_node = node.get('value')
                    if value_node:
                        return self._extract_literal_value(value_node)

        return None

    def _extract_literal_value(self, node: Dict) -> Optional[str]:
        """从AST节点提取字面量值"""
        if node.get('nodeType') == 'Literal':
            value = node.get('value', '')
            value = value.strip('"').strip("'")
            return value
        elif node.get('nodeType') == 'FunctionCall':
            # 处理类型转换
            args = node.get('arguments', [])
            if args:
                return self._extract_literal_value(args[0])

        return None

    def _extract_param_info(self, arg_node: Dict) -> ParamInfo:
        """提取参数信息"""
        param_type = self._infer_type_from_ast(arg_node)
        is_literal = arg_node.get('nodeType') == 'Literal'
        literal_val = self._extract_literal_value(arg_node) if is_literal else None
        expression = self._reconstruct_expression(arg_node)
        dependencies = self._find_dependencies(arg_node)

        return ParamInfo(
            ast_node=arg_node,
            type=param_type,
            is_literal=is_literal,
            literal_value=literal_val,
            expression=expression,
            dependencies=dependencies
        )

    def _infer_type_from_ast(self, node: Dict) -> str:
        """从AST节点推断类型"""
        node_type = node.get('nodeType', '')

        if node_type == 'Literal':
            kind = node.get('kind', '')
            if kind == 'number':
                return 'uint256'
            elif kind == 'string':
                return 'string'
            elif kind == 'bool':
                return 'bool'

        elif node_type == 'Identifier':
            # 需要查找变量声明
            return 'uint256'  # 默认

        elif node_type == 'FunctionCall':
            # 函数调用的返回类型
            expr = node.get('expression', {})
            if expr.get('nodeType') == 'MemberAccess':
                member = expr.get('memberName', '')
                if member == 'balanceOf':
                    return 'uint256'
            elif expr.get('nodeType') == 'Identifier':
                func_name = expr.get('name', '')
                if func_name == 'address':
                    return 'address'

        return 'uint256'  # 默认

    def _reconstruct_expression(self, node: Dict) -> str:
        """重构表达式字符串"""
        node_type = node.get('nodeType', '')

        if node_type == 'Literal':
            return str(node.get('value', '')).strip('"').strip("'")

        elif node_type == 'Identifier':
            return node.get('name', '')

        elif node_type == 'BinaryOperation':
            left = self._reconstruct_expression(node.get('leftExpression', {}))
            right = self._reconstruct_expression(node.get('rightExpression', {}))
            op = node.get('operator', '')
            return f"({left} {op} {right})"

        elif node_type == 'UnaryOperation':
            sub_expr = self._reconstruct_expression(node.get('subExpression', {}))
            op = node.get('operator', '')
            prefix = node.get('prefix', True)
            return f"{op}{sub_expr}" if prefix else f"{sub_expr}{op}"

        elif node_type == 'FunctionCall':
            expr = node.get('expression', {})
            args = node.get('arguments', [])

            if expr.get('nodeType') == 'MemberAccess':
                obj = self._reconstruct_expression(expr.get('expression', {}))
                member = expr.get('memberName', '')
                args_str = ', '.join(self._reconstruct_expression(arg) for arg in args)
                return f"{obj}.{member}({args_str})"
            elif expr.get('nodeType') == 'Identifier':
                func_name = expr.get('name', '')
                args_str = ', '.join(self._reconstruct_expression(arg) for arg in args)
                return f"{func_name}({args_str})"

        elif node_type == 'MemberAccess':
            obj = self._reconstruct_expression(node.get('expression', {}))
            member = node.get('memberName', '')
            return f"{obj}.{member}"

        elif node_type == 'IndexAccess':
            base = self._reconstruct_expression(node.get('baseExpression', {}))
            index = self._reconstruct_expression(node.get('indexExpression', {}))
            return f"{base}[{index}]"

        return '<complex_expression>'

    def _find_dependencies(self, node: Dict) -> List[str]:
        """查找表达式依赖的变量"""
        dependencies = []

        for sub_node in self._walk_ast(node):
            if sub_node.get('nodeType') == 'Identifier':
                var_name = sub_node.get('name', '')
                if var_name and var_name not in dependencies:
                    dependencies.append(var_name)

        return dependencies

    def _find_loop_context(self, call_node: Dict) -> Optional[LoopInfo]:
        """查找调用是否在循环中"""
        node_id = call_node.get('id')
        if node_id is None:
            return None

        # 向上遍历父节点
        current = call_node
        while True:
            parent_id = None
            for nid, parent in self.node_parents.items():
                if any(child.get('id') == current.get('id') for child in self._walk_ast(parent)):
                    parent_id = parent.get('id')
                    current = parent
                    break

            if parent_id is None:
                break

            node_type = current.get('nodeType', '')
            if node_type in ['ForStatement', 'WhileStatement', 'DoWhileStatement']:
                return LoopInfo(
                    count=self._extract_loop_count(current),
                    type=node_type.replace('Statement', '').lower(),
                    ast_node=current
                )

        return None

    def _extract_loop_count(self, loop_node: Dict) -> Optional[int]:
        """提取循环次数"""
        node_type = loop_node.get('nodeType', '')

        if node_type == 'ForStatement':
            # 分析条件: i < N
            condition = loop_node.get('condition', {})
            if condition.get('nodeType') == 'BinaryOperation':
                right = condition.get('rightExpression', {})
                if right.get('nodeType') == 'Literal':
                    try:
                        return int(right.get('value', '0'))
                    except:
                        pass

        elif node_type == 'WhileStatement':
            # 类似处理
            condition = loop_node.get('condition', {})
            if condition.get('nodeType') == 'BinaryOperation':
                right = condition.get('rightExpression', {})
                if right.get('nodeType') == 'Literal':
                    try:
                        return int(right.get('value', '0'))
                    except:
                        pass

        return None

    def _offset_to_line(self, offset: int) -> int:
        """将字符偏移转换为行号"""
        current_offset = 0
        for line_num, line in enumerate(self.source_lines, 1):
            current_offset += len(line) + 1  # +1 for newline
            if current_offset > offset:
                return line_num
        return 0

    def identify_vulnerable_contracts(self) -> List[ContractInfo]:
        """识别被攻击的合约"""
        candidates = []

        for contract_addr, calls in self.call_graph.external_calls.items():
            call_count = len(calls)
            unique_functions = len(set(c.function_name for c in calls))
            in_loops = sum(1 for c in calls if c.loop_context is not None)
            has_state_change = any(self._is_state_changing(c) for c in calls)

            # 评分模型
            score = (
                call_count * 2 +
                unique_functions * 3 +
                in_loops * 5 +
                (10 if has_state_change else 0)
            )

            candidates.append(ContractInfo(
                address=contract_addr,
                name=self._infer_contract_name(contract_addr),
                call_count=call_count,
                functions=list(set(c.function_name for c in calls)),
                score=score
            ))

        return sorted(candidates, key=lambda x: x.score, reverse=True)

    def _is_state_changing(self, call_info: CallInfo) -> bool:
        """判断是否为状态修改函数"""
        state_change_keywords = {
            'deposit', 'withdraw', 'mint', 'burn', 'transfer',
            'swap', 'borrow', 'repay', 'flash', 'bond', 'debond',
            'stake', 'unstake', 'claim', 'liquidate'
        }
        return any(kw in call_info.function_name.lower() for kw in state_change_keywords)

    def _infer_contract_name(self, address: str) -> str:
        """从变量声明推断合约名称"""
        # 在AST中查找地址对应的变量名
        for node in self._walk_ast(self.ast):
            if node.get('nodeType') == 'VariableDeclaration':
                value_node = node.get('value')
                if value_node:
                    addr = self._extract_literal_value(value_node)
                    if addr and addr.lower() == address.lower():
                        return node.get('name', 'Unknown')

        return 'Unknown'

    def extract_address_declarations(self) -> List[AddressDeclaration]:
        """
        提取所有地址类型的变量声明

        解析模式:
        1. IToken private constant token = IToken(0x123...);
        2. address private constant WETH = 0x456...;
        3. IUniswapV2Pair pair = IUniswapV2Pair(0x789...);

        Returns:
            List[AddressDeclaration]: 地址声明列表
        """
        declarations = []

        for node in self._walk_ast(self.ast):
            if node.get('nodeType') != 'VariableDeclaration':
                continue

            var_name = node.get('name')
            if not var_name:
                continue

            # 获取类型信息
            type_node = node.get('typeName', {})
            type_name = type_node.get('name', '')  # 可能是address或接口名

            # 检查是否为地址类型或自定义接口类型
            is_address_type = (
                type_name == 'address' or
                type_name.startswith('I') or  # 接口命名约定
                'contract' in type_node.get('nodeType', '').lower()
            )

            if not is_address_type:
                continue

            # 获取值节点
            value_node = node.get('value')
            if not value_node:
                continue

            # 提取地址值(可能被类型转换包裹)
            address_value = self._extract_address_from_value(value_node)
            if not address_value:
                continue

            # 确保地址格式正确
            if not address_value.startswith('0x'):
                address_value = '0x' + address_value

            # 提取修饰符
            is_constant = node.get('constant', False)
            is_immutable = node.get('mutability') == 'immutable'
            visibility = node.get('visibility', 'internal')

            # 计算行号
            src = node.get('src', '')
            line_number = 0
            if src:
                try:
                    offset = int(src.split(':')[0])
                    line_number = self._offset_to_line(offset)
                except:
                    pass

            # 推断接口名
            interface_name = None
            if type_name and type_name != 'address':
                interface_name = type_name

            declarations.append(AddressDeclaration(
                variable_name=var_name,
                interface_name=interface_name,
                address=address_value,
                is_constant=is_constant,
                is_immutable=is_immutable,
                visibility=visibility,
                line_number=line_number
            ))

        logger.debug(f"提取到{len(declarations)}个地址声明")
        return declarations

    def _extract_address_from_value(self, value_node: Dict) -> Optional[str]:
        """
        从值节点提取地址

        处理模式:
        1. 直接字面量: 0x123...
        2. 类型转换: address(0x123...)
        3. 接口转换: IToken(0x123...)
        """
        node_type = value_node.get('nodeType', '')

        # 模式1: 直接字面量
        if node_type == 'Literal':
            return self._extract_literal_value(value_node)

        # 模式2/3: 函数调用(类型转换)
        if node_type == 'FunctionCall':
            # 提取第一个参数(被转换的地址)
            args = value_node.get('arguments', [])
            if args:
                arg_node = args[0]

                # 递归处理嵌套转换: IToken(address(0x123...))
                return self._extract_address_from_value(arg_node)

        return None


# =============================================================================
# 改进2: Dynamic Storage Layout Inference
# =============================================================================

class StateDiffAnalyzer:
    """状态差异分析器（从V2继承并增强）"""

    def __init__(self, protocol_dir: Path):
        self.protocol_dir = protocol_dir
        self.state_before = self._load_json("attack_state.json")
        self.state_after = self._load_json("attack_state_after.json")
        self.addresses_info = self._load_json("addresses.json")

        # 初始化Storage布局推断器
        self.layout_inferrer = None  # 延迟初始化

    def _load_json(self, filename: str) -> Optional[Dict]:
        file_path = self.protocol_dir / filename
        if not file_path.exists():
            return None
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                # 如果是addresses.json,转换为地址->信息的映射
                if filename == "addresses.json" and isinstance(data, list):
                    return {item['address'].lower(): item for item in data if 'address' in item}
                return data
        except Exception as e:
            logger.warning(f"加载{filename}失败: {e}")
            return None

    def _find_address_by_name(self, search_name: str) -> Optional[str]:
        """
        增强的名称查找 - 使用aliases支持模糊匹配

        查找优先级:
        1. 精确匹配 name 字段
        2. 精确匹配 symbol 字段
        3. 精确匹配 aliases 中的任意别名
        4. 部分匹配 name 或 aliases

        Args:
            search_name: 要查找的名称(如 'wBARL', 'IwBARL', 'BARL')

        Returns:
            匹配的地址(小写),如果未找到返回None
        """
        if not self.addresses_info:
            return None

        search_lower = search_name.lower()

        # 第一轮: 精确匹配
        for addr, info in self.addresses_info.items():
            name = info.get('name', '')
            if name and name.lower() == search_lower:
                return addr

            symbol = info.get('symbol', '')
            if symbol and symbol.lower() == search_lower:
                return addr

            aliases = info.get('aliases', [])
            if aliases:
                for alias in aliases:
                    if alias and alias.lower() == search_lower:
                        return addr

        # 第二轮: 部分匹配
        for addr, info in self.addresses_info.items():
            name = info.get('name', '')
            if name and (search_lower in name.lower() or name.lower() in search_lower):
                return addr

            aliases = info.get('aliases', [])
            if aliases:
                for alias in aliases:
                    if alias and (search_lower in alias.lower() or alias.lower() in search_lower):
                        return addr

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
        """分析合约的slot变化"""
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

                is_new_slot = (before_int == 0 and after_int != 0)
                is_cleared_slot = (before_int != 0 and after_int == 0)

                if before_int != 0:
                    change_pct = abs(change) / before_int * 100
                elif after_int != 0:
                    change_pct = 100.0
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

        return sorted(changes, key=lambda x: x['change_abs'], reverse=True)


class StorageLayoutInferrer:
    """动态Storage布局推断器"""

    def __init__(self, state_analyzer: StateDiffAnalyzer, addresses_info: Dict):
        self.state_analyzer = state_analyzer
        self.addresses_info = addresses_info or {}
        self.layout_cache: Dict[str, StorageLayout] = {}

    def infer_layout(self, contract_addr: str) -> StorageLayout:
        """推断合约的storage布局"""
        if contract_addr in self.layout_cache:
            return self.layout_cache[contract_addr]

        layout = StorageLayout(contract_address=contract_addr)

        # 获取所有slot变化
        slot_changes = self.state_analyzer.analyze_slot_changes(contract_addr)

        # 方法1: 基于ERC20标准行为推断
        if self._is_erc20_contract(contract_addr):
            self._infer_erc20_slots(contract_addr, slot_changes, layout)

        # 方法2: 基于slot值特征推断
        self._infer_from_value_patterns(slot_changes, layout)

        # 方法3: 基于跨合约关联推断
        self._infer_from_cross_contract_correlation(contract_addr, slot_changes, layout)

        self.layout_cache[contract_addr] = layout
        return layout

    def _is_erc20_contract(self, contract_addr: str) -> bool:
        """判断是否为ERC20合约"""
        # 优先使用链上数据补全的 is_erc20 字段
        if self.addresses_info:
            for addr, info in self.addresses_info.items():
                if addr.lower() == contract_addr.lower():
                    # 1. 直接使用is_erc20字段(来自OnChainDataFetcher)
                    is_erc20 = info.get('is_erc20')
                    if is_erc20 is not None:
                        return is_erc20

                    # 2. 基于semantic_type判断
                    semantic_type = info.get('semantic_type', '')
                    if semantic_type in ['wrapped_token', 'erc20_token']:
                        return True

                    # 3. 基于symbol判断(如果有symbol则很可能是token)
                    symbol = info.get('symbol')
                    if symbol:
                        return True

                    # 4. 回退: 基于name关键词判断
                    name = info.get('name', '').lower()
                    keywords = ['token', 'coin', 'erc20', 'weth', 'wbtc', 'dai', 'usdc', 'usdt', 'barl']
                    if any(kw in name for kw in keywords):
                        return True

        # 通过slot变化判断
        slot_changes = self.state_analyzer.analyze_slot_changes(contract_addr)
        has_supply_like = any(
            10**18 <= abs(c['before']) <= 10**30 or 10**18 <= abs(c['after']) <= 10**30
            for c in slot_changes if not self._is_mapping_slot(c['slot'])
        )
        # 降低阈值:至少有1个mapping slot即可
        has_mappings = sum(1 for c in slot_changes if self._is_mapping_slot(c['slot'])) >= 1

        return has_supply_like and has_mappings

    def _infer_erc20_slots(self, contract_addr: str, slot_changes: List[Dict], layout: StorageLayout):
        """推断ERC20合约的关键slot"""

        # 1. 识别totalSupply slot
        supply_candidates = []
        for change in slot_changes:
            slot = change['slot']
            if not self._is_mapping_slot(slot):
                value_before = change['before']
                value_after = change['after']

                if 10**18 <= value_before <= 10**30 or 10**18 <= value_after <= 10**30:
                    confidence = self._verify_supply_hypothesis(contract_addr, slot, change)
                    supply_candidates.append((slot, confidence))

        if supply_candidates:
            best_slot = max(supply_candidates, key=lambda x: x[1])[0]
            layout.add_variable(best_slot, 'totalSupply', 'uint256', confidence=supply_candidates[0][1])

        # 2. 识别balances mapping
        balance_slots = []
        for change in slot_changes:
            slot = change['slot']
            if self._is_mapping_slot(slot):
                base_slot, key = self._reverse_mapping_slot(contract_addr, slot, change)
                if base_slot is not None:
                    found = False
                    for idx, (bs, name, keys) in enumerate(balance_slots):
                        if bs == base_slot:
                            balance_slots[idx] = (bs, name, keys + [key])
                            found = True
                            break
                    if not found:
                        balance_slots.append((base_slot, 'balances', [key]))

        if balance_slots:
            best_mapping = max(balance_slots, key=lambda x: len(x[2]))
            layout.add_mapping(best_mapping[0], 'balances', 'address', 'uint256',
                             known_keys=best_mapping[2])

    def _reverse_mapping_slot(self, contract_addr: str, slot_hash: str, change: Dict) -> Tuple[Optional[int], Optional[str]]:
        """尝试反推mapping的base slot和key"""
        # 标准化slot_hash为hex格式
        if not slot_hash.startswith('0x'):
            slot_hash_hex = hex(int(slot_hash))
        else:
            slot_hash_hex = slot_hash

        # 遍历可能的base slot（0-20）
        for base_slot in range(20):
            # 遍历addresses.json中的所有地址作为候选key
            for addr in self.addresses_info.keys():
                computed_slot = compute_mapping_slot(addr, base_slot)
                if computed_slot.lower() == slot_hash_hex.lower():
                    return (base_slot, addr)

        return (None, None)

    def _verify_supply_hypothesis(self, contract_addr: str, slot: str, change: Dict) -> float:
        """验证totalSupply假设的置信度"""
        confidence = 0.5

        # 检查1: 数值是否在合理范围
        value = max(change['before'], change['after'])
        if 10**18 <= value <= 10**27:
            confidence += 0.2

        # 检查2: 变化量是否与转账事件匹配
        transfer_total = self._sum_transfer_amounts(contract_addr)
        if transfer_total > 0:
            change_abs = change['change_abs']
            ratio = change_abs / transfer_total
            if 0.9 <= ratio <= 1.1:
                confidence += 0.3

        return min(confidence, 1.0)

    def _sum_transfer_amounts(self, contract_addr: str) -> int:
        """从addresses.json中所有地址的余额变化推算转账总量"""
        total = 0

        # 简化实现：返回最大的变化量作为估计
        slot_changes = self.state_analyzer.analyze_slot_changes(contract_addr)
        if slot_changes:
            total = max(c['change_abs'] for c in slot_changes if self._is_mapping_slot(c['slot']))

        return total

    def _infer_from_value_patterns(self, slot_changes: List[Dict], layout: StorageLayout):
        """基于值的模式推断slot语义"""
        for change in slot_changes:
            slot = change['slot']
            value_before = change['before']
            value_after = change['after']

            # 跳过已识别的slot
            if slot in layout.variables:
                continue

            # 布尔值检测
            if value_before in [0, 1] and value_after in [0, 1]:
                layout.add_variable(slot, f'flag_{slot}', 'bool', confidence=0.7)

            # 地址检测
            elif 0 < value_before < 2**160 or 0 < value_after < 2**160:
                layout.add_variable(slot, f'address_{slot}', 'address', confidence=0.6)

            # 时间戳检测
            elif 1600000000 < value_before < 2000000000:
                layout.add_variable(slot, f'timestamp_{slot}', 'uint256', confidence=0.7)

    def _infer_from_cross_contract_correlation(self, contract_addr: str, slot_changes: List[Dict], layout: StorageLayout):
        """基于跨合约关联推断slot语义"""
        # 查找相关合约
        related_contracts = self._find_related_contracts(contract_addr)

        for related_addr in related_contracts:
            related_changes = self.state_analyzer.analyze_slot_changes(related_addr)

            for change in slot_changes:
                for related_change in related_changes:
                    correlation = self._compute_change_correlation(change, related_change)

                    if correlation > 0.8:
                        semantic = self._infer_paired_slot_semantic(
                            contract_addr, related_addr, change, related_change
                        )
                        if semantic and change['slot'] not in layout.variables:
                            layout.add_variable(change['slot'], semantic, 'uint256',
                                              confidence=correlation)

    def _find_related_contracts(self, contract_addr: str) -> List[str]:
        """查找相关合约"""
        related = []

        for addr in self.addresses_info.keys():
            if addr.lower() == contract_addr.lower():
                continue

            # 检查是否都有storage变化
            if self.state_analyzer.analyze_slot_changes(addr):
                related.append(addr)

        return related

    def _compute_change_correlation(self, change1: Dict, change2: Dict) -> float:
        """计算两个slot变化的相关性"""
        # 简化：比较变化方向和幅度
        if change1['change_direction'] != change2['change_direction']:
            return 0.0

        if change1['change_abs'] == 0 or change2['change_abs'] == 0:
            return 0.0

        ratio = change1['change_abs'] / change2['change_abs']
        if 0.5 <= ratio <= 2.0:
            return 0.8
        elif 0.1 <= ratio <= 10.0:
            return 0.5

        return 0.3

    def _infer_paired_slot_semantic(self, addr1: str, addr2: str, change1: Dict, change2: Dict) -> Optional[str]:
        """推断配对slot的语义"""
        # 例如：LP pair的reserve0/reserve1
        info1 = self.addresses_info.get(addr1, {})
        info2 = self.addresses_info.get(addr2, {})

        name1 = info1.get('name', '').lower()
        name2 = info2.get('name', '').lower()

        if 'pair' in name1 or 'pool' in name1:
            if 'reserve' not in [v.name for v in layout_cache.get(addr1, StorageLayout(addr1)).variables.values()]:
                return 'reserve'

        return None

    def _is_mapping_slot(self, slot: str) -> bool:
        """判断slot是否为mapping的派生slot"""
        try:
            slot_int = int(slot, 16) if slot.startswith('0x') else int(slot)
            return slot_int > 2**200
        except:
            return False


# =============================================================================
# 改进3: Symbolic Execution Parameter Evaluator
# =============================================================================

class ContractProxy:
    """合约代理 - 从状态数据中读取合约状态"""

    def __init__(self, address: str, state_analyzer: StateDiffAnalyzer):
        self.address = address
        self.state_analyzer = state_analyzer
        self.storage = state_analyzer.get_contract_storage(address, before=True)

        # 尝试推断合约类型
        if state_analyzer.layout_inferrer:
            self.layout = state_analyzer.layout_inferrer.infer_layout(address)
        else:
            self.layout = StorageLayout(contract_address=address)

    def call(self, method_name: str, *args) -> Any:
        """模拟合约方法调用"""

        # ERC20标准方法
        if method_name == 'balanceOf':
            return self._balanceOf(args[0] if args else None)
        elif method_name == 'totalSupply':
            return self._totalSupply()
        elif method_name == 'decimals':
            return 18

        # UniswapV2 Pair方法
        elif method_name == 'getReserves':
            return self._getReserves()

        # 通用slot读取
        else:
            raise ValueError(f"不支持的方法: {method_name}")

    def _balanceOf(self, holder_address: str) -> int:
        """读取地址余额"""
        if not holder_address:
            return 0

        # 从layout获取balances mapping的base slot
        for mapping in self.layout.mappings.values():
            if mapping.name == 'balances':
                slot = compute_mapping_slot(holder_address, mapping.base_slot)
                if slot in self.storage:
                    return to_int(self.storage[slot])

        # 回退：尝试常见的slot 0
        slot = compute_mapping_slot(holder_address, 0)
        if slot in self.storage:
            return to_int(self.storage[slot])

        return 0

    def _totalSupply(self) -> int:
        """读取总供应量"""
        # 从layout获取totalSupply的slot
        for var in self.layout.variables.values():
            if var.name == 'totalSupply':
                slot = var.slot
                if slot in self.storage:
                    return to_int(self.storage[slot])

        # 回退：尝试常见的slot 2
        if '2' in self.storage:
            return to_int(self.storage['2'])

        return 0

    def _getReserves(self) -> Tuple[int, int, int]:
        """读取Uniswap pair reserves"""
        # Uniswap V2的reserves通常在slot 8
        if '8' in self.storage:
            value = to_int(self.storage['8'])
            # reserves打包在一个slot中
            reserve0 = value & ((1 << 112) - 1)
            reserve1 = (value >> 112) & ((1 << 112) - 1)
            timestamp = (value >> 224) & ((1 << 32) - 1)
            return (reserve0, reserve1, timestamp)

        return (0, 0, 0)


class BoundMethod:
    """绑定方法 - 延迟求值"""
    def __init__(self, obj: ContractProxy, method_name: str):
        self.obj = obj
        self.method_name = method_name

    def __call__(self, *args):
        return self.obj.call(self.method_name, *args)


class SymbolicParameterEvaluator:
    """参数表达式符号执行求值器"""

    def __init__(self, ast_analyzer: Optional[SolidityASTAnalyzer], state_analyzer: StateDiffAnalyzer):
        self.ast_analyzer = ast_analyzer
        self.state_analyzer = state_analyzer
        self.variable_env: Dict[str, Any] = {}
        self._build_environment()

    def _build_environment(self):
        """构建执行环境"""
        # 1. 从addresses.json获取合约地址映射
        if self.state_analyzer.addresses_info:
            for addr, info in self.state_analyzer.addresses_info.items():
                name = info.get('name', '')
                if name:
                    self.variable_env[name] = ContractProxy(addr, self.state_analyzer)

        # 2. 从AST获取常量定义
        if self.ast_analyzer:
            for node in self.ast_analyzer._walk_ast(self.ast_analyzer.ast):
                if node.get('nodeType') == 'VariableDeclaration':
                    if node.get('constant') or node.get('immutable'):
                        name = node.get('name', '')
                        value_node = node.get('value')
                        if value_node:
                            try:
                                value = self._evaluate_ast_node(value_node)
                                self.variable_env[name] = value
                            except:
                                pass

    def evaluate(self, param_info: ParamInfo) -> Optional[int]:
        """求值参数表达式"""
        ast_node = param_info.ast_node

        try:
            result = self._evaluate_ast_node(ast_node)
            return self._to_int(result)
        except Exception as e:
            logger.debug(f"参数求值失败: {param_info.expression}, 错误: {e}")
            return None

    def _evaluate_ast_node(self, node: Dict) -> Any:
        """递归求值AST节点"""
        node_type = node.get('nodeType', '')

        # 字面量
        if node_type == 'Literal':
            return self._parse_literal(node)

        # 标识符
        elif node_type == 'Identifier':
            var_name = node.get('name', '')
            if var_name in self.variable_env:
                return self.variable_env[var_name]
            else:
                raise ValueError(f"未知变量: {var_name}")

        # 二元运算
        elif node_type == 'BinaryOperation':
            return self._evaluate_binary_op(node)

        # 一元运算
        elif node_type == 'UnaryOperation':
            return self._evaluate_unary_op(node)

        # 函数调用
        elif node_type == 'FunctionCall':
            return self._evaluate_function_call(node)

        # 成员访问
        elif node_type == 'MemberAccess':
            return self._evaluate_member_access(node)

        # 索引访问
        elif node_type == 'IndexAccess':
            return self._evaluate_index_access(node)

        else:
            raise ValueError(f"不支持的节点类型: {node_type}")

    def _evaluate_binary_op(self, node: Dict) -> Any:
        """求值二元运算"""
        operator = node.get('operator', '')
        left = self._evaluate_ast_node(node.get('leftExpression', {}))
        right = self._evaluate_ast_node(node.get('rightExpression', {}))

        # 算术运算
        if operator == '+':
            return left + right
        elif operator == '-':
            return left - right
        elif operator == '*':
            return left * right
        elif operator == '/':
            return left // right
        elif operator == '%':
            return left % right
        elif operator == '**':
            return left ** right
        elif operator == '<<':
            return left << right
        elif operator == '>>':
            return left >> right

        # 比较运算
        elif operator == '<':
            return left < right
        elif operator == '>':
            return left > right
        elif operator == '<=':
            return left <= right
        elif operator == '>=':
            return left >= right
        elif operator == '==':
            return left == right
        elif operator == '!=':
            return left != right

        # 逻辑运算
        elif operator == '&&':
            return left and right
        elif operator == '||':
            return left or right

        else:
            raise ValueError(f"不支持的运算符: {operator}")

    def _evaluate_unary_op(self, node: Dict) -> Any:
        """求值一元运算"""
        operator = node.get('operator', '')
        sub_expr = self._evaluate_ast_node(node.get('subExpression', {}))

        if operator == '-':
            return -sub_expr
        elif operator == '+':
            return +sub_expr
        elif operator == '!':
            return not sub_expr
        else:
            raise ValueError(f"不支持的一元运算符: {operator}")

    def _evaluate_function_call(self, node: Dict) -> Any:
        """求值函数调用"""
        expression = node.get('expression', {})

        # MemberAccess: object.method(...)
        if expression.get('nodeType') == 'MemberAccess':
            obj = self._evaluate_ast_node(expression.get('expression', {}))
            method_name = expression.get('memberName', '')
            arguments = [self._evaluate_ast_node(arg) for arg in node.get('arguments', [])]

            # 调用代理对象的方法
            if isinstance(obj, ContractProxy):
                return obj.call(method_name, *arguments)
            elif isinstance(obj, BoundMethod):
                return obj(*arguments)
            else:
                raise ValueError(f"无法调用 {type(obj)}.{method_name}")

        # 直接函数调用或类型转换
        elif expression.get('nodeType') == 'Identifier':
            func_name = expression.get('name', '')
            arguments = [self._evaluate_ast_node(arg) for arg in node.get('arguments', [])]

            # 类型转换
            if func_name in ['address', 'uint256', 'int256', 'bytes32']:
                return arguments[0] if arguments else 0

            # 全局函数
            elif func_name == 'keccak256':
                # 简化实现
                return 0

            else:
                raise ValueError(f"不支持的函数: {func_name}")

        else:
            raise ValueError(f"不支持的函数调用: {expression}")

    def _evaluate_member_access(self, node: Dict) -> Any:
        """求值成员访问"""
        obj = self._evaluate_ast_node(node.get('expression', {}))
        member_name = node.get('memberName', '')

        if isinstance(obj, ContractProxy):
            return BoundMethod(obj, member_name)
        else:
            raise ValueError(f"无法访问 {type(obj)}.{member_name}")

    def _evaluate_index_access(self, node: Dict) -> Any:
        """求值索引访问"""
        base = self._evaluate_ast_node(node.get('baseExpression', {}))
        index = self._evaluate_ast_node(node.get('indexExpression', {}))

        if isinstance(base, (list, tuple)):
            return base[index]
        else:
            raise ValueError(f"无法索引 {type(base)}")

    def _parse_literal(self, node: Dict) -> Any:
        """解析字面量"""
        kind = node.get('kind', '')
        value_str = node.get('value', '')

        if kind == 'number':
            # 处理科学计数法
            if 'e' in value_str.lower():
                parts = value_str.lower().split('e')
                base = int(parts[0].replace('_', ''))
                exponent = int(parts[1])
                return base * (10 ** exponent)
            else:
                return int(value_str.replace('_', ''), 0)

        elif kind == 'string':
            return value_str

        elif kind == 'bool':
            return value_str.lower() == 'true'

        else:
            return value_str

    def _to_int(self, value: Any) -> int:
        """将求值结果转为整数"""
        if isinstance(value, int):
            return value
        elif isinstance(value, bool):
            return 1 if value else 0
        elif isinstance(value, str):
            if value.startswith('0x'):
                return int(value, 16)
            return int(value)
        else:
            raise ValueError(f"无法转换为整数: {type(value)}")


# =============================================================================
# 集成V3约束生成器（复用V2的部分逻辑）
# =============================================================================

# 由于篇幅限制，将在实际使用时集成
# 这里直接使用简化版本，在main函数中调用

# =============================================================================
# 主函数
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="参数-状态约束提取器 V3 - 基于AST、动态布局推断、符号执行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 单个协议
  python extract_param_state_constraints_v3.py --protocol BarleyFinance_exp --year-month 2024-01

  # 批量处理
  python extract_param_state_constraints_v3.py --batch --filter 2024-01

V3改进:
  1. AST-based攻击脚本解析（替代正则表达式）
  2. 动态Storage布局推断（逆向分析ERC20/mapping slot）
  3. 符号执行参数求值（精确计算复杂表达式）
        """
    )

    parser.add_argument('--protocol', help='协议名称')
    parser.add_argument('--year-month', help='年月')
    parser.add_argument('--batch', action='store_true', help='批量模式')
    parser.add_argument('--filter', help='年月过滤器')
    parser.add_argument('--output', help='自定义输出路径')
    parser.add_argument('--test-ast', action='store_true', help='测试AST解析')
    parser.add_argument('--test-layout', action='store_true', help='测试布局推断')
    parser.add_argument('--test-eval', action='store_true', help='测试参数求值')

    args = parser.parse_args()

    repo_root = Path(__file__).parent

    # 测试模式
    if args.test_ast and args.protocol and args.year_month:
        logger.info("=== 测试AST解析 ===")
        test_ast_parsing(repo_root, args.protocol, args.year_month)
        return

    if args.test_layout and args.protocol and args.year_month:
        logger.info("=== 测试Storage布局推断 ===")
        test_layout_inference(repo_root, args.protocol, args.year_month)
        return

    if args.test_eval and args.protocol and args.year_month:
        logger.info("=== 测试参数求值 ===")
        test_parameter_evaluation(repo_root, args.protocol, args.year_month)
        return

    logger.error("V3完整集成正在开发中")
    logger.info("当前可用测试模式:")
    logger.info("  --test-ast: 测试AST解析")
    logger.info("  --test-layout: 测试Storage布局推断")
    logger.info("  --test-eval: 测试参数求值")


def test_ast_parsing(repo_root: Path, protocol: str, year_month: str):
    """测试AST解析功能"""
    script_path = repo_root / "src" / "test" / year_month / f"{protocol}.sol"

    if not script_path.exists():
        logger.error(f"脚本不存在: {script_path}")
        return

    try:
        analyzer = SolidityASTAnalyzer(script_path, repo_root)

        logger.success("AST获取成功")
        logger.info(f"  AST节点数: {len(analyzer._walk_ast(analyzer.ast))}")

        # 识别被攻击合约
        candidates = analyzer.identify_vulnerable_contracts()

        logger.info(f"\n识别到 {len(candidates)} 个候选被攻击合约:")
        for i, contract in enumerate(candidates[:5], 1):
            logger.info(f"  {i}. {contract.name} ({contract.address})")
            logger.info(f"     - 调用次数: {contract.call_count}")
            logger.info(f"     - 函数: {', '.join(contract.functions)}")
            logger.info(f"     - 评分: {contract.score:.1f}")

        # 显示函数调用
        if candidates:
            best = candidates[0]
            calls = analyzer.call_graph.external_calls[best.address]
            logger.info(f"\n{best.name} 的函数调用:")
            for call in calls[:10]:
                loop_info = f" [循环{call.loop_context.count}次]" if call.loop_context else ""
                logger.info(f"  Line {call.line_number}: {call.function_name}(...){loop_info}")
                for param in call.parameters[:3]:
                    logger.info(f"    - {param.expression} ({param.type})")

    except Exception as e:
        logger.error(f"AST解析失败: {e}")
        import traceback
        traceback.print_exc()


def test_layout_inference(repo_root: Path, protocol: str, year_month: str):
    """测试Storage布局推断"""
    protocol_dir = repo_root / "extracted_contracts" / year_month / protocol

    if not protocol_dir.exists():
        logger.error(f"协议目录不存在: {protocol_dir}")
        return

    try:
        state_analyzer = StateDiffAnalyzer(protocol_dir)

        if not state_analyzer.state_before:
            logger.error("attack_state.json不存在")
            return

        # 初始化布局推断器
        state_analyzer.layout_inferrer = StorageLayoutInferrer(
            state_analyzer,
            state_analyzer.addresses_info
        )

        # 分析所有有变化的合约
        addresses = state_analyzer.state_before.get('addresses', {})
        logger.info(f"分析 {len(addresses)} 个合约的storage布局:\n")

        # 优先分析有名称的合约
        named_addresses = [
            addr for addr in addresses.keys()
            if state_analyzer.addresses_info.get(addr.lower(), {}).get('name') is not None
        ]
        other_addresses = [
            addr for addr in addresses.keys()
            if state_analyzer.addresses_info.get(addr.lower(), {}).get('name') is None
        ]

        # 优先处理有名称的前10个,然后是其他的前5个
        for addr in (named_addresses[:10] + other_addresses[:5]):
            slot_changes = state_analyzer.analyze_slot_changes(addr)
            if not slot_changes:
                continue

            name = state_analyzer.addresses_info.get(addr.lower(), {}).get('name', 'Unknown')
            logger.info(f"合约: {name} ({addr})")
            logger.info(f"  Slot变化数: {len(slot_changes)}")

            # 推断布局
            layout = state_analyzer.layout_inferrer.infer_layout(addr)

            logger.info(f"  推断的变量:")
            for slot, var in layout.variables.items():
                logger.info(f"    slot {slot}: {var.name} ({var.type}) - 置信度{var.confidence:.2f}")

            logger.info(f"  推断的mapping:")
            for base_slot, mapping in layout.mappings.items():
                logger.info(f"    slot {base_slot}: {mapping.name} ({mapping.key_type}=>{mapping.value_type})")
                logger.info(f"      已知keys: {len(mapping.known_keys)}个")

            logger.info("")

    except Exception as e:
        logger.error(f"布局推断失败: {e}")
        import traceback
        traceback.print_exc()


def test_parameter_evaluation(repo_root: Path, protocol: str, year_month: str):
    """测试参数求值"""
    script_path = repo_root / "src" / "test" / year_month / f"{protocol}.sol"
    protocol_dir = repo_root / "extracted_contracts" / year_month / protocol

    if not script_path.exists() or not protocol_dir.exists():
        logger.error("脚本或协议目录不存在")
        return

    try:
        # 1. AST解析
        ast_analyzer = SolidityASTAnalyzer(script_path, repo_root)
        candidates = ast_analyzer.identify_vulnerable_contracts()

        if not candidates:
            logger.error("未识别到被攻击合约")
            return

        # 2. 状态分析
        state_analyzer = StateDiffAnalyzer(protocol_dir)
        state_analyzer.layout_inferrer = StorageLayoutInferrer(
            state_analyzer,
            state_analyzer.addresses_info
        )

        # 3. 符号执行求值
        evaluator = SymbolicParameterEvaluator(ast_analyzer, state_analyzer)

        logger.info(f"变量环境: {len(evaluator.variable_env)} 个变量")
        for name in list(evaluator.variable_env.keys())[:10]:
            obj = evaluator.variable_env[name]
            logger.info(f"  {name}: {type(obj).__name__}")

        # 4. 求值参数
        best_contract = candidates[0]
        calls = ast_analyzer.call_graph.external_calls[best_contract.address]

        logger.info(f"\n对 {best_contract.name} 的函数调用进行参数求值:\n")

        for call in calls[:5]:
            logger.info(f"函数: {call.function_name}")
            for param in call.parameters:
                logger.info(f"  表达式: {param.expression}")
                value = evaluator.evaluate(param)
                if value is not None:
                    logger.success(f"  求值结果: {value:,} (0x{value:x})")
                else:
                    logger.warning(f"  求值失败")
            logger.info("")

    except Exception as e:
        logger.error(f"参数求值测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

