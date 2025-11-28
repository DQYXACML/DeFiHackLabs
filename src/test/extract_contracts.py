#!/usr/bin/env python3
"""
DeFi攻击合约源码提取工具

功能:
1. 静态分析: 从攻击脚本中提取显式定义的合约地址
2. 动态分析: 运行forge test获取完整的合约调用链
3. 源码下载: 从区块浏览器API下载已验证的合约源码

作者: Claude Code
版本: 1.0.0
"""

import re
import json
import os
import subprocess
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pathlib import Path
from typing import Any, List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import logging
import tempfile
import shutil
from contextlib import contextmanager
import threading
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio

# 导入OnChainDataFetcher
try:
    import sys
    # 添加项目根目录到Python路径
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from onchain_data_fetcher import OnChainDataFetcher
    ONCHAIN_FETCHER_AVAILABLE = True
except ImportError as e:
    ONCHAIN_FETCHER_AVAILABLE = False
    logger.warning(f"OnChainDataFetcher不可用: {e}")
    logger.info("将跳过链上数据补全功能")

# ============================================================================
# 配置
# ============================================================================

# API Keys配置 (写死在脚本中)
# 注意: Etherscan API V2统一支持多个网络,包括BSC!
# 支持多个key并发,每个key限速5次/秒
DEFAULT_API_KEYS = {
    "etherscan": [
        "2DTB79CHTEJ6PEDCTEINC8GV3IHUXHGP9A",
        "NNBK8BWF9FCBY77Y2C1S5GG5CACNJIAQ8C",
        "K6RUIHP3NJ72D4F3MNVG8XMI6R8EE1JSJD",
        "SMZQJGY9IVWYKUMK2SIME6F15HGD8F8I6C",
        "KIHJWZGZ4YD8DNJBQTH5SUZA83U9YW9F21"
    ],
    # 其他独立网络的Key可以在这里添加(也支持列表):
    # "arbiscan": ["YOUR_ARBISCAN_KEY_1", "YOUR_ARBISCAN_KEY_2"],
    # "polygonscan": ["YOUR_POLYGONSCAN_KEY"],
}

# 区块浏览器API配置 (V2)
# 注意: Etherscan已迁移到V2 API,需要chainid参数
EXPLORER_APIS = {
    "mainnet": {
        "name": "Etherscan",
        "api_url": "https://api.etherscan.io/v2/api",
        "web_url": "https://etherscan.io",
        "chainid": 1,
        "api_key_name": "etherscan",
        "rpc_url": "https://lb.drpc.live/ethereum/Avduh2iIjEAksBUYtd4wP1NUPObEnwYR76WEFhW5UfFk"
    },
    "arbitrum": {
        "name": "Arbiscan",
        "api_url": "https://api.etherscan.io/v2/api",
        "web_url": "https://arbiscan.io",
        "chainid": 42161,
        "api_key_name": "etherscan",
        "rpc_url": "https://lb.drpc.live/arbitrum/Avduh2iIjEAksBUYtd4wP1NUPObEnwYR76WEFhW5UfFk"
    },
    "bsc": {
        "name": "BscScan",
        "api_url": "https://api.etherscan.io/v2/api",
        "web_url": "https://bscscan.com",
        "chainid": 56,
        "api_key_name": "etherscan",
        "rpc_url": "https://lb.drpc.live/bsc/Avduh2iIjEAksBUYtd4wP1NUPObEnwYR76WEFhW5UfFk"
    },
    "base": {
        "name": "BaseScan",
        "api_url": "https://api.etherscan.io/v2/api",
        "web_url": "https://basescan.org",
        "chainid": 8453,
        "api_key_name": "etherscan",
        "rpc_url": "https://lb.drpc.live/base/Avduh2iIjEAksBUYtd4wP1NUPObEnwYR76WEFhW5UfFk"
    },
    "optimism": {
        "name": "Optimism Etherscan",
        "api_url": "https://api.etherscan.io/v2/api",
        "web_url": "https://optimistic.etherscan.io",
        "chainid": 10,
        "api_key_name": "etherscan",
        "rpc_url": "https://lb.drpc.live/optimism/Avduh2iIjEAksBUYtd4wP1NUPObEnwYR76WEFhW5UfFk"
    },
    "blast": {
        "name": "BlastScan",
        "api_url": "https://api.etherscan.io/v2/api",
        "web_url": "https://blastscan.io",
        "chainid": 81457,
        "api_key_name": "etherscan",
        "rpc_url": "https://lb.drpc.live/blast/Avduh2iIjEAksBUYtd4wP1NUPObEnwYR76WEFhW5UfFk"
    },
    "polygon": {
        "name": "PolygonScan",
        "api_url": "https://api.etherscan.io/v2/api",
        "web_url": "https://polygonscan.com",
        "chainid": 137,
        "api_key_name": "etherscan",
        "rpc_url": "https://lb.drpc.live/polygon/Avduh2iIjEAksBUYtd4wP1NUPObEnwYR76WEFhW5UfFk"
    },
    "avalanche": {
        "name": "SnowTrace",
        "api_url": "https://api.snowtrace.io/v2/api",
        "web_url": "https://snowtrace.io",
        "chainid": 43114,
        "api_key_name": "snowtrace",
        "rpc_url": "https://lb.drpc.live/avalanche/Avduh2iIjEAksBUYtd4wP1NUPObEnwYR76WEFhW5UfFk"
    },
    "fantom": {
        "name": "FTMScan",
        "api_url": "https://api.ftmscan.com/v2/api",
        "web_url": "https://ftmscan.com",
        "chainid": 250,
        "api_key_name": "ftmscan",
        "rpc_url": "https://lb.drpc.live/fantom/Avduh2iIjEAksBUYtd4wP1NUPObEnwYR76WEFhW5UfFk"
    },
}

# forge 测试默认跳过的脚本（已知编译问题）
DEFAULT_SKIP_TESTS = [
    "src/test/2025-05/Corkprotocol_exp.sol",
    "src/test/2024-11/proxy_b7e1_exp.sol",
]

# 免费API限流配置
API_RATE_LIMIT = 5  # 5次/秒
API_RETRY_TIMES = 3
API_RETRY_DELAY = 2  # 秒

# 日志配置
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# ============================================================================
# 路径配置
# ============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
try:
    PROJECT_ROOT = SCRIPT_DIR.parents[1]
except IndexError:
    PROJECT_ROOT = SCRIPT_DIR
DEFAULT_TEST_DIR = PROJECT_ROOT / 'src/test'
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / 'extracted_contracts'
DEFAULT_LOG_FILE = PROJECT_ROOT / 'logs' / 'extract_contracts.log'

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ContractAddress:
    """合约地址信息"""
    address: str
    name: Optional[str] = None
    chain: Optional[str] = None
    source: str = "unknown"  # static/dynamic/comment
    context: Optional[str] = None  # 提取上下文

    # 链上数据补全字段(由OnChainDataFetcher填充)
    onchain_name: Optional[str] = None  # 从链上获取的合约名称
    symbol: Optional[str] = None  # ERC20 token symbol
    decimals: Optional[int] = None  # ERC20 decimals
    is_erc20: Optional[bool] = None  # 是否为ERC20代币
    semantic_type: Optional[str] = None  # 语义类型: wrapped_token, uniswap_v2_pair等
    aliases: Optional[List[str]] = None  # 别名列表(包含symbol, interface name等)

    def __hash__(self):
        return hash(self.address.lower())

    def __eq__(self, other):
        if isinstance(other, ContractAddress):
            return self.address.lower() == other.address.lower()
        return False


@dataclass
class ExploitScript:
    """攻击脚本信息"""
    file_path: Path
    name: str
    date_dir: str
    chain: Optional[str] = None
    block_number: Optional[int] = None
    loss_amount: Optional[str] = None
    attack_tx: Optional[str] = None


@dataclass
class ExecutionSummary:
    """执行摘要"""
    total_scripts: int = 0
    successful_scripts: int = 0
    failed_scripts: int = 0
    total_addresses: int = 0
    verified_contracts: int = 0
    unverified_contracts: int = 0
    bytecode_only_contracts: int = 0  # 仅下载字节码的合约数
    api_calls: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


# ============================================================================
# 静态分析模块
# ============================================================================

class StaticAnalyzer:
    """静态分析器 - 从源码中提取合约地址"""

    # 以太坊地址正则
    ETH_ADDRESS_PATTERN = re.compile(r'0x[a-fA-F0-9]{40}')

    # 常见的地址定义模式
    ADDRESS_PATTERNS = [
        # Type VAR = Type(payable(0x...)) - 优先匹配嵌套模式，提取外层Type
        re.compile(r'(\w+)\s+(?:private|public|internal)?\s*(\w+)\s*=\s*\w+\(payable\((0x[a-fA-F0-9]{40})\)\)'),
        # address constant NAME = 0x...
        re.compile(r'address\s+(?:constant\s+)?(?:public\s+)?(\w+)\s*=\s*(0x[a-fA-F0-9]{40})'),
        # Type [visibility] constant VAR = Type(0x...) - 支持 private/public/internal constant
        re.compile(r'(\w+)\s+(?:private|public|internal)?\s*constant\s+(\w+)\s*=\s*\w+\((0x[a-fA-F0-9]{40})\)'),
        # Type VAR = Type(0x...) - 标准类型转换
        re.compile(r'(\w+)\s+(?:private|public|internal)?\s*(\w+)\s*=\s*\w+\((0x[a-fA-F0-9]{40})\)'),
        # Interface(0x...) - 最宽松的模式，捕获上下文但不提取名称
        re.compile(r'(\w+)\((0x[a-fA-F0-9]{40})\)'),
    ]

    # 名称黑名单 - wrapper函数和关键字，不应作为合约名
    NAME_BLACKLIST = {
        'payable', 'address', 'uint256', 'uint', 'int', 'bytes', 'string',
        'bool', 'bytes32', 'bytes4', 'vm', 'cheats', 'console', 'console2',
        'CheatCodes', 'Vm', 'Test',
        # 修饰符关键字
        'private', 'public', 'internal', 'external', 'constant', 'immutable'
    }

    # 注释中的关键字 - 扩展版
    COMMENT_KEYWORDS = [
        'Attacker',
        'Attack Contract',
        'Attack_Contract',      # 下划线版本
        'Vulnerable Contract',
        'Vulnerable_Contract',  # 下划线版本
        'Vuln Contract',        # 缩写版本
        'Vuln_Contract',
        'Target Contract',
        'Target',
        'Victim',
        'Protected Contract',
        'Exploited Contract',
    ]

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.StaticAnalyzer')

    def analyze_script(self, script: ExploitScript) -> Tuple[List[ContractAddress], str]:
        """
        分析单个脚本

        Returns:
            (地址列表, 链类型)
        """
        self.logger.info(f"静态分析: {script.name}")

        try:
            with open(script.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            self.logger.error(f"读取文件失败 {script.file_path}: {e}")
            return [], None

        addresses = []

        # 1. 从注释中提取地址
        addresses.extend(self._extract_from_comments(content))

        # 2. 从代码中提取常量定义
        addresses.extend(self._extract_from_code(content))

        # 3. 提取链类型
        chain = self._extract_chain(content)

        # 4. 提取区块号
        block_number = self._extract_block_number(content)
        script.block_number = block_number
        script.chain = chain

        # 去重
        unique_addresses = list(dict.fromkeys(addresses))

        self.logger.info(f"  静态提取到 {len(unique_addresses)} 个地址")
        return unique_addresses, chain

    def _extract_from_comments(self, content: str) -> List[ContractAddress]:
        """从注释中提取地址"""
        addresses = []
        lines = content.split('\n')

        for line in lines:
            if not line.strip().startswith('//'):
                continue

            # 检查是否包含关键字
            for keyword in self.COMMENT_KEYWORDS:
                if keyword in line:
                    # 提取URL和地址
                    urls = re.findall(r'https://[^\s]+', line)
                    for url in urls:
                        # 从URL中提取地址
                        match = self.ETH_ADDRESS_PATTERN.search(url)
                        if match:
                            addr = match.group(0)
                            chain = self._chain_from_url(url)
                            addresses.append(ContractAddress(
                                address=addr,
                                name=keyword.replace(' ', '_'),
                                chain=chain,
                                source='comment',
                                context=line.strip()
                            ))

                    # 直接从注释中提取地址
                    if not urls:
                        match = self.ETH_ADDRESS_PATTERN.search(line)
                        if match:
                            addr = match.group(0)
                            addresses.append(ContractAddress(
                                address=addr,
                                name=keyword.replace(' ', '_'),
                                source='comment',
                                context=line.strip()
                            ))

        return addresses

    def _extract_from_code(self, content: str) -> List[ContractAddress]:
        """从代码中提取地址 - 增强版，支持智能名称过滤"""
        addresses = []

        # 提取address constant定义
        for pattern in self.ADDRESS_PATTERNS:
            matches = pattern.finditer(content)
            for match in matches:
                groups = match.groups()
                # 查找地址和可能的名称
                addr = None
                potential_names = []  # 收集所有潜在名称，稍后智能选择

                for g in groups:
                    if g and g.startswith('0x') and len(g) == 42:
                        addr = g
                    elif g and not g.startswith('0x'):
                        potential_names.append(g)

                if addr:
                    # 智能选择名称：
                    # 1. 优先选择非黑名单的名称
                    # 2. 如果有多个候选，优先选择类型名（大写开头）而非变量名
                    # 3. 如果都在黑名单中，从context中提取
                    name = self._select_best_name(potential_names, match.group(0))

                    addresses.append(ContractAddress(
                        address=addr,
                        name=name,
                        source='static',
                        context=match.group(0)
                    ))

        return addresses

    def _select_best_name(self, candidates: List[str], context: str) -> Optional[str]:
        """
        从候选名称中智能选择最佳名称

        Args:
            candidates: 候选名称列表
            context: 原始匹配的上下文字符串

        Returns:
            最佳名称或None
        """
        if not candidates:
            return self._extract_name_from_context(context)

        # 过滤黑名单
        valid_names = [name for name in candidates if name.lower() not in self.NAME_BLACKLIST]

        if not valid_names:
            # 所有候选都在黑名单中，尝试从context提取
            return self._extract_name_from_context(context)

        # 如果只有一个有效名称，直接返回
        if len(valid_names) == 1:
            return valid_names[0]

        # 有多个有效名称，优先选择类型名（大写开头，通常是接口或合约类型）
        type_names = [name for name in valid_names if name[0].isupper()]
        if type_names:
            return type_names[0]

        # 否则返回第一个
        return valid_names[0]

    def _extract_name_from_context(self, context: str) -> Optional[str]:
        """
        从上下文字符串中智能提取合约名称

        处理模式：
        - IWiseLending w = IWiseLending(payable(0x...)) → 提取 "IWiseLending"
        - payable(0x...) → None (无法提取有效名称)
        - IPancakeRouter(0x...) → 提取 "IPancakeRouter"
        """
        # 尝试提取所有大写开头的标识符（可能是类型名）
        type_pattern = re.compile(r'([A-Z][A-Za-z0-9_]*)\s*\(')
        matches = type_pattern.findall(context)

        # 过滤黑名单
        valid_matches = [m for m in matches if m.lower() not in self.NAME_BLACKLIST]

        if valid_matches:
            return valid_matches[0]

        return None

    def _extract_chain(self, content: str) -> Optional[str]:
        """
        提取链类型 - 增强版

        支持多种 createSelectFork 调用格式:
        1. vm.createSelectFork("mainnet", ...)
        2. vm.createSelectFork('mainnet', ...)
        3. CheatCodes(vm).createSelectFork("mainnet", ...)
        4. 从注释中的区块浏览器URL推断
        """
        # 模式1: 标准格式 createSelectFork("chain", ...) 或 createSelectFork('chain', ...)
        match = re.search(r'createSelectFork\s*\(\s*["\'](\w+)["\']', content)
        if match:
            return match.group(1)

        # 模式2: 链式调用 .createSelectFork("chain", ...)
        match = re.search(r'\.createSelectFork\s*\(\s*["\'](\w+)["\']', content)
        if match:
            return match.group(1)

        # 模式3: 从注释中的区块浏览器URL推断 (fallback)
        chain = self._infer_chain_from_comments(content)
        if chain:
            self.logger.debug(f"从注释URL推断链类型: {chain}")
            return chain

        return None

    def _infer_chain_from_comments(self, content: str) -> Optional[str]:
        """
        从注释中的区块浏览器URL推断链类型

        扫描注释中的 etherscan/bscscan 等URL，推断链类型
        """
        chain_url_patterns = [
            (r'etherscan\.io', 'mainnet'),
            (r'bscscan\.com', 'bsc'),
            (r'arbiscan\.io', 'arbitrum'),
            (r'basescan\.org', 'base'),
            (r'optimistic\.etherscan\.io', 'optimism'),
            (r'polygonscan\.com', 'polygon'),
            (r'ftmscan\.com', 'fantom'),
            (r'snowtrace\.io', 'avalanche'),
            (r'gnosisscan\.io', 'gnosis'),
            (r'celoscan\.io', 'celo'),
            (r'moonriver\.moonscan\.io', 'moonriver'),
            (r'blastscan\.io', 'blast'),
            (r'lineascan\.build', 'linea'),
            (r'explorer\.mantle\.xyz', 'mantle'),
            (r'seitrace\.com', 'sei'),
        ]

        for pattern, chain in chain_url_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return chain

        return None

    def _extract_block_number(self, content: str) -> Optional[int]:
        """提取区块号"""
        match = re.search(r'blocknumToForkFrom\s*=\s*(\d+)', content)
        if match:
            return int(match.group(1))
        return None

    def _chain_from_url(self, url: str) -> Optional[str]:
        """从URL识别链类型"""
        if 'etherscan.io' in url:
            return 'mainnet'
        elif 'bscscan.com' in url:
            return 'bsc'
        elif 'arbiscan.io' in url:
            return 'arbitrum'
        elif 'basescan.org' in url:
            return 'base'
        return None


# ============================================================================
# 动态分析模块
# ============================================================================

class DynamicAnalyzer:
    """动态分析器 - 运行forge test并解析trace"""

    # 匹配CALL指令的地址 - 格式: [gas] address::function(...)
    CALL_PATTERN = re.compile(r'\[(\d+)\]\s+(0x[a-fA-F0-9]{40})::\w+')
    # 匹配合约创建 - 格式: → new ContractName@address 或 → address
    CREATE_PATTERN = re.compile(r'→\s+(?:new\s+\w+@)?(0x[a-fA-F0-9]{40})')
    # 匹配trace段落中的任意地址(用于兜底捕获)
    HEX_ADDRESS_PATTERN = re.compile(r'0x[a-fA-F0-9]{40}')
    TRACES_SECTION_PATTERN = re.compile(r'Traces:\s*(.+)', re.S)

    # 无效地址黑名单 - 这些地址不是真实合约,避免浪费RPC查询
    INVALID_ADDRESSES = {
        '0x0000000000000000000000000000000000000000',  # 零地址
        '0x0000000000000000000000000000000000000001',  # 预编译合约: ecrecover
        '0x0000000000000000000000000000000000000002',  # 预编译合约: sha256
        '0x0000000000000000000000000000000000000003',  # 预编译合约: ripemd160
        '0x0000000000000000000000000000000000000004',  # 预编译合约: identity
        '0x0000000000000000000000000000000000000005',  # 预编译合约: modexp
        '0x0000000000000000000000000000000000000006',  # 预编译合约: ecadd
        '0x0000000000000000000000000000000000000007',  # 预编译合约: ecmul
        '0x0000000000000000000000000000000000000008',  # 预编译合约: ecpairing
        '0x0000000000000000000000000000000000000009',  # 预编译合约: blake2f
        '0x000000000000000000000000000000000000000a',  # 预编译合约: kzg
        '0x00000000000000000000000000000000000000bad',  # 标记地址
        '0xffffffffffffffffffffffffffffffffffffffff',  # 最大地址
        '0x000000000000000000000000000000000000dead',  # 销毁地址
        '0x0000000000000000000000000000000000001111',  # 测试地址
        '0x0000000000000000000000000000000000002222',  # 测试地址
    }

    def __init__(self, skip_tests: Optional[List[str]] = None):
        self.logger = logging.getLogger(__name__ + '.DynamicAnalyzer')
        self.project_root = PROJECT_ROOT
        self.skip_tests = skip_tests or DEFAULT_SKIP_TESTS

    @classmethod
    def is_valid_address(cls, address: str) -> bool:
        """
        检查地址是否可能是有效合约

        过滤掉:
        1. 黑名单中的已知无效地址
        2. 包含连续8个以上零的地址 (可能是混合数据)
        3. 格式不正确的地址

        Returns:
            True if address is likely valid, False otherwise
        """
        if not address or len(address) != 42:
            return False

        addr_lower = address.lower()

        # 检查黑名单
        if addr_lower in cls.INVALID_ADDRESSES:
            return False

        # 过滤包含连续8个以上零的地址 (可能是calldata混合数据)
        # 例如: 0x65c189ab000000000000ce6bcf68ce8419e70000
        # 跳过前10个字符 (0x + 前8位可能是有效前缀)
        if '00000000' in addr_lower[10:]:
            return False

        # 检查是否全为0或全为f
        hex_part = addr_lower[2:]
        if hex_part == '0' * 40 or hex_part == 'f' * 40:
            return False

        return True

    def analyze_script(self, script: ExploitScript) -> List[ContractAddress]:
        """
        运行forge test并提取调用的所有合约

        Returns:
            地址列表
        """
        self.logger.info(f"动态分析: {script.name}")

        try:
            # 运行forge test (默认 -vvvv)
            output = self._run_forge_test(script.file_path)

            if output is None:
                self.logger.warning(f"  测试运行失败,跳过动态分析")
                return []

            addresses = self._parse_trace(output)
            if not addresses:
                # 自动尝试使用 -vvvvv 以输出更完整的调用栈
                self.logger.info("  未解析到trace，使用 -vvvvv 重新运行以强制输出")
                trace_output = self._run_forge_test(script.file_path, extra_flags=['-vvvvv'])
                if trace_output:
                    addresses = self._parse_trace(trace_output)
                    output = trace_output  # 便于后续判断日志状态

            if not addresses and 'Traces:' not in output:
                self.logger.warning("  forge 输出中仍未包含 Traces，可考虑在测试中加入 emit/log 触发 trace")

            self.logger.info(f"  动态提取到 {len(addresses)} 个地址")
            return addresses

        except Exception as e:
            self.logger.error(f"动态分析失败: {e}")
            return []

    def _run_forge_test(self, test_file: Path, timeout: int = 300,
                        extra_flags: Optional[List[str]] = None) -> Optional[str]:
        """
        运行forge test

        Args:
            test_file: 测试文件路径
            timeout: 超时时间(秒)

        Returns:
            测试输出或None(如果失败)
        """
        try:
            try:
                match_path = test_file.relative_to(self.project_root)
            except ValueError:
                self.logger.error(f"  测试文件不在项目根目录内: {test_file}")
                return None

            flags = extra_flags if extra_flags is not None else ['-vvvv']
            cmd = [
                'forge', 'test',
                '--match-path', str(match_path)
            ]

            # 跳过已知存在编译/执行问题的测试脚本，避免阻塞当前分析
            for skip in self.skip_tests:
                if skip:
                    cmd.extend(['--skip', skip])

            cmd.extend(flags)

            working_dir = self.project_root
            self.logger.debug(f"  执行命令: {' '.join(cmd)}")
            self.logger.debug(f"  工作目录: {working_dir}")

            result = subprocess.run(
                cmd,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # 即使测试失败,也可能有trace输出
            output = result.stdout + result.stderr

            if result.returncode != 0:
                self.logger.warning(f"  测试返回非零状态码: {result.returncode}")
                trimmed_output = output.strip()
                if trimmed_output:
                    lines = trimmed_output.splitlines()
                    max_lines = 120
                    if len(lines) > max_lines:
                        trimmed_output = "\n".join(lines[-max_lines:])
                        self.logger.warning(f"  forge 输出(末尾 {max_lines} 行):\n{trimmed_output}")
                    else:
                        self.logger.warning(f"  forge 输出:\n{trimmed_output}")
                # 检查是否有trace输出
                if 'Traces:' not in output:
                    return None

            return output

        except subprocess.TimeoutExpired:
            self.logger.error(f"  测试超时({timeout}秒)")
            return None
        except FileNotFoundError:
            self.logger.error("  forge命令未找到,请确保已安装Foundry")
            return None
        except Exception as e:
            self.logger.error(f"  运行forge test失败: {e}")
            return None

    @contextmanager
    def _isolated_project(self, test_file: Path) -> Tuple[Path, Path]:
        """为指定测试脚本创建隔离的Foundry工程环境"""
        temp_dir = Path(tempfile.mkdtemp(prefix="extractor_"))
        try:
            self._copy_project_configs(temp_dir)

            files_to_copy = self._collect_dependencies(test_file)
            for src in files_to_copy:
                if not src.exists():
                    continue
                try:
                    rel_path = src.relative_to(self.project_root)
                except ValueError:
                    continue
                dest = temp_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

            try:
                relative_test = test_file.relative_to(self.project_root)
            except ValueError:
                raise RuntimeError(f"测试文件不在项目根目录内: {test_file}")

            match_path = (temp_dir / relative_test).resolve()
            yield temp_dir, match_path.relative_to(temp_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _copy_project_configs(self, temp_dir: Path):
        """复制Foundry配置文件与依赖库"""
        for name in ('foundry.toml', 'remappings.txt'):
            src = self.project_root / name
            if src.exists():
                shutil.copy2(src, temp_dir / name)

        lib_src = self.project_root / 'lib'
        lib_dest = temp_dir / 'lib'
        if lib_src.exists() and not lib_dest.exists():
            try:
                os.symlink(lib_src, lib_dest, target_is_directory=True)
            except OSError:
                shutil.copytree(lib_src, lib_dest)

    IMPORT_PATTERN = re.compile(r'import\s+(?:\{[^}]*\}\s+from\s+)?["\']([^"\']+)["\'];?')

    def _collect_dependencies(self, test_file: Path) -> Set[Path]:
        """递归收集测试脚本的相对依赖"""
        to_process = [test_file.resolve()]
        collected: Set[Path] = set()

        while to_process:
            current = to_process.pop()
            if current in collected:
                continue
            collected.add(current)

            try:
                content = current.read_text()
            except Exception:
                continue

            for match in self.IMPORT_PATTERN.finditer(content):
                import_path = match.group(1)
                dependency = self._resolve_import_path(current, import_path)
                if dependency and dependency.suffix == '.sol' and dependency.exists():
                    to_process.append(dependency.resolve())

        return collected

    def _resolve_import_path(self, current_file: Path, import_path: str) -> Optional[Path]:
        """解析导入路径,支持相对路径以及src/test/script前缀"""
        if import_path.startswith('.'):
            return (current_file.parent / import_path).resolve()
        if import_path.startswith('src/'):
            return (self.project_root / import_path).resolve()
        if import_path.startswith('test/'):
            return (self.project_root / import_path).resolve()
        if import_path.startswith('script/'):
            return (self.project_root / import_path).resolve()
        return None

    def _parse_trace(self, output: str) -> List[ContractAddress]:
        """解析trace输出提取合约地址"""
        addresses = []
        seen = set()
        filtered_count = 0  # 统计过滤掉的无效地址数量

        # 提取CALL调用的合约
        for match in self.CALL_PATTERN.finditer(output):
            gas = match.group(1)
            address = match.group(2)

            # 过滤无效地址
            if not self.is_valid_address(address):
                filtered_count += 1
                continue

            if address.lower() not in seen:
                seen.add(address.lower())
                addresses.append(ContractAddress(
                    address=address,
                    source='dynamic',
                    context=f'called with gas {gas}'
                ))

        # 提取CREATE创建的合约
        for match in self.CREATE_PATTERN.finditer(output):
            address = match.group(1)

            # 过滤无效地址
            if not self.is_valid_address(address):
                filtered_count += 1
                continue

            if address.lower() not in seen:
                seen.add(address.lower())
                addresses.append(ContractAddress(
                    address=address,
                    source='dynamic',
                    context='contract created'
                ))

        # 额外解析Traces段落中出现的所有地址
        trace_body = self._extract_traces_body(output)
        if trace_body:
            for match in self.HEX_ADDRESS_PATTERN.finditer(trace_body):
                address = match.group(0)

                # 过滤无效地址
                if not self.is_valid_address(address):
                    filtered_count += 1
                    continue

                lowered = address.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                addresses.append(ContractAddress(
                    address=address,
                    source='dynamic',
                    context='trace reference'
                ))

        if filtered_count > 0:
            self.logger.debug(f"  已过滤 {filtered_count} 个无效地址 (零地址/预编译/混合数据)")

        return addresses

    def _extract_traces_body(self, output: str) -> Optional[str]:
        """提取 forge 输出中的 Traces 段落"""
        match = self.TRACES_SECTION_PATTERN.search(output)
        if not match:
            return None
        return match.group(1)


# ============================================================================
# API Key池管理模块 (支持多Key并发)
# ============================================================================

class APIKeyPool:
    """
    API Key池管理器 - 支持多个key并发请求,每个key独立限流

    特性:
    - 多个API Key并发使用
    - 每个Key独立限流(默认5次/秒)
    - 线程安全的Key获取/归还
    - 避免死锁和资源冲突
    """

    def __init__(self, keys: List[str], rate_limit: int = 5):
        """
        初始化API Key池

        Args:
            keys: API Key列表
            rate_limit: 每个key的限速(次/秒)
        """
        self.keys = keys
        self.rate_limit = rate_limit
        self.logger = logging.getLogger(__name__ + '.APIKeyPool')

        # 为每个key创建独立的限流状态
        self.key_states = {
            key: {
                'last_call_time': 0.0,
                'lock': threading.Lock(),
                'call_count': 0
            }
            for key in keys
        }

        # 使用Queue管理可用的key
        self.available_keys = Queue()
        for key in keys:
            self.available_keys.put(key)

        # 统计信息
        self.total_calls = 0
        self.stats_lock = threading.Lock()

        self.logger.info(f"初始化API Key池: {len(keys)} 个key, 限速 {rate_limit} 次/秒")

    @contextmanager
    def acquire_key(self, timeout: float = 30.0):
        """
        获取一个可用的API Key (上下文管理器)

        Args:
            timeout: 获取key的超时时间(秒)

        Yields:
            API Key字符串

        使用示例:
            with key_pool.acquire_key() as api_key:
                # 使用api_key发起请求
                response = requests.get(url, params={'apikey': api_key})
        """
        key = None
        try:
            # 从队列中获取一个可用的key
            try:
                key = self.available_keys.get(timeout=timeout)
            except Empty:
                raise RuntimeError(f"获取API Key超时({timeout}秒),所有key都在使用中")

            # 应用该key的限流
            self._apply_rate_limit(key)

            # 返回key供使用
            yield key

        finally:
            # 确保key被归还到队列
            if key is not None:
                self.available_keys.put(key)

    def _apply_rate_limit(self, key: str):
        """对指定key应用限流"""
        state = self.key_states[key]

        with state['lock']:
            now = time.time()
            elapsed = now - state['last_call_time']

            # 计算需要等待的时间
            min_interval = 1.0 / self.rate_limit
            if elapsed < min_interval:
                sleep_time = min_interval - elapsed
                time.sleep(sleep_time)

            # 更新状态
            state['last_call_time'] = time.time()
            state['call_count'] += 1

            # 更新总调用次数
            with self.stats_lock:
                self.total_calls += 1

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self.stats_lock:
            key_stats = {
                key: state['call_count']
                for key, state in self.key_states.items()
            }
            return {
                'total_calls': self.total_calls,
                'key_count': len(self.keys),
                'per_key_calls': key_stats
            }


# ============================================================================
# 代理合约检测模块
# ============================================================================

class ProxyDetector:
    """代理合约检测器 - 检测并解析各种代理模式"""

    # EIP-1967: Logic contract (Implementation)
    EIP1967_LOGIC_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"

    # EIP-1967: Beacon contract
    EIP1967_BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"

    # EIP-1822: UUPS Proxiable
    EIP1822_LOGIC_SLOT = "0xc5f16f0fcc639fa48a6947836d9850f504798523bf8c9a3a87d5876cf622bcf7"

    # OpenZeppelin: Implementation slot (for older versions)
    OZ_IMPLEMENTATION_SLOT = "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3"

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def detect_proxy(self, address: str, chain: str) -> Optional[Dict[str, Any]]:
        """
        检测合约是否为代理,并返回实现合约地址

        Args:
            address: 合约地址
            chain: 链类型

        Returns:
            代理信息字典或None: {
                'is_proxy': True,
                'proxy_type': 'EIP1967' | 'EIP1822' | 'Beacon' | 'Custom',
                'implementation': '0x...',
                'beacon': '0x...' (仅Beacon代理)
            }
        """
        if chain not in EXPLORER_APIS:
            return None

        api_config = EXPLORER_APIS[chain]
        rpc_url = api_config.get('rpc_url')

        if not rpc_url:
            self.logger.debug(f"  未配置RPC URL用于链: {chain}, 跳过代理检测")
            return None

        try:
            # 1. 检查 EIP-1967 Logic Slot
            impl_address = self._get_storage_at(rpc_url, address, self.EIP1967_LOGIC_SLOT)
            if impl_address and impl_address != "0x" + "0" * 40:
                return {
                    'is_proxy': True,
                    'proxy_type': 'EIP1967',
                    'implementation': impl_address
                }

            # 2. 检查 EIP-1967 Beacon Slot
            beacon_address = self._get_storage_at(rpc_url, address, self.EIP1967_BEACON_SLOT)
            if beacon_address and beacon_address != "0x" + "0" * 40:
                # Beacon代理需要再从Beacon合约中获取实现地址
                impl_from_beacon = self._get_implementation_from_beacon(rpc_url, beacon_address)
                if impl_from_beacon:
                    return {
                        'is_proxy': True,
                        'proxy_type': 'Beacon',
                        'implementation': impl_from_beacon,
                        'beacon': beacon_address
                    }

            # 3. 检查 EIP-1822 UUPS Slot
            impl_address = self._get_storage_at(rpc_url, address, self.EIP1822_LOGIC_SLOT)
            if impl_address and impl_address != "0x" + "0" * 40:
                return {
                    'is_proxy': True,
                    'proxy_type': 'EIP1822',
                    'implementation': impl_address
                }

            # 4. 检查 OpenZeppelin 旧版本 Slot
            impl_address = self._get_storage_at(rpc_url, address, self.OZ_IMPLEMENTATION_SLOT)
            if impl_address and impl_address != "0x" + "0" * 40:
                return {
                    'is_proxy': True,
                    'proxy_type': 'OpenZeppelin',
                    'implementation': impl_address
                }

            # 未检测到代理
            return None

        except Exception as e:
            self.logger.debug(f"  代理检测失败: {e}")
            return None

    def _get_storage_at(self, rpc_url: str, address: str, slot: str) -> Optional[str]:
        """
        通过 eth_getStorageAt 读取storage slot

        Returns:
            地址字符串(0x...)或None
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_getStorageAt",
                "params": [address, slot, "latest"],
                "id": 1
            }

            # 优化: 减少代理检测超时从10秒到3秒
            response = requests.post(rpc_url, json=payload, timeout=3)
            response.raise_for_status()

            data = response.json()

            if 'result' not in data:
                return None

            storage_value = data['result']

            # storage值是32字节,地址是最后20字节
            if storage_value and len(storage_value) >= 42:
                # 提取最后40个十六进制字符(20字节)作为地址
                address_hex = "0x" + storage_value[-40:]

                # 检查是否为零地址
                if address_hex == "0x" + "0" * 40:
                    return None

                return address_hex

            return None

        except Exception as e:
            self.logger.debug(f"  读取storage失败: {e}")
            return None

    def _get_implementation_from_beacon(self, rpc_url: str, beacon_address: str) -> Optional[str]:
        """
        从Beacon合约中获取实现合约地址

        Beacon合约通常有 implementation() 函数 (selector: 0x5c60da1b)
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{
                    "to": beacon_address,
                    "data": "0x5c60da1b"  # implementation()
                }, "latest"],
                "id": 1
            }

            # 优化: 减少Beacon查询超时从10秒到3秒
            response = requests.post(rpc_url, json=payload, timeout=3)
            response.raise_for_status()

            data = response.json()

            if 'result' not in data:
                return None

            result = data['result']

            # 返回值是32字节,地址是最后20字节
            if result and len(result) >= 42:
                address_hex = "0x" + result[-40:]

                if address_hex == "0x" + "0" * 40:
                    return None

                return address_hex

            return None

        except Exception as e:
            self.logger.debug(f"  从Beacon获取实现地址失败: {e}")
            return None


# ============================================================================
# 源码下载模块
# ============================================================================

def batch_check_contracts_exist(addresses: List[str], rpc_url: str,
                                timeout: int = 3, max_workers: int = 10) -> Set[str]:
    """
    批量快速检查哪些地址是真实合约 (并发检查)

    Args:
        addresses: 地址列表
        rpc_url: RPC节点URL
        timeout: 每个RPC调用的超时时间(秒)
        max_workers: 最大并发数

    Returns:
        有效合约地址的集合
    """
    if not addresses:
        return set()

    valid_contracts = set()
    logger.info(f"  批量预检查 {len(addresses)} 个地址的合约存在性 (并发数: {max_workers})...")

    def quick_check(addr: str) -> Optional[str]:
        """快速检查单个地址是否为合约"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_getCode",
                "params": [addr, "latest"],
                "id": 1
            }

            response = requests.post(rpc_url, json=payload, timeout=timeout)
            response.raise_for_status()

            data = response.json()
            bytecode = data.get('result', '0x')

            # 检查是否有字节码 (不是0x或0x0)
            if bytecode and bytecode not in ('0x', '0x0', ''):
                return addr
            return None

        except Exception as e:
            logger.debug(f"    检查地址 {addr[:10]}... 失败: {e}")
            return None

    # 并发检查
    start_time = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(quick_check, addr): addr for addr in addresses}

        for future in as_completed(futures):
            result = future.result()
            if result:
                valid_contracts.add(result.lower())

    elapsed = time.perf_counter() - start_time
    logger.info(f"  ✓ 预检查完成: {len(valid_contracts)}/{len(addresses)} 个有效合约, 耗时 {elapsed:.2f}秒")

    return valid_contracts


class SourceDownloader:
    """源码下载器 - 从区块浏览器下载合约源码(支持多Key并发)"""

    def __init__(self, api_keys: Optional[Dict[str, Any]] = None):
        # 使用传入的API Keys,如果没有则使用默认配置
        self.api_keys = api_keys or DEFAULT_API_KEYS
        self.logger = logging.getLogger(__name__ + '.SourceDownloader')

        # 初始化代理检测器
        self.proxy_detector = ProxyDetector(self.logger)

        # 创建带重试机制的requests session
        self.session = self._create_retry_session()

        # 为每个key类型创建KeyPool
        self.key_pools = {}
        for key_name, keys in self.api_keys.items():
            # 兼容旧格式(单个key字符串)和新格式(key列表)
            if isinstance(keys, str):
                keys = [keys]
            elif isinstance(keys, list):
                keys = keys
            else:
                self.logger.warning(f"未知的key格式: {key_name}, 跳过")
                continue

            # 创建该类型的KeyPool
            self.key_pools[key_name] = APIKeyPool(keys, rate_limit=API_RATE_LIMIT)
            self.logger.info(f"为 {key_name} 创建Key池: {len(keys)} 个key")

    def _create_retry_session(self) -> requests.Session:
        """创建带重试机制的requests session"""
        session = requests.Session()

        # 配置重试策略
        retry_strategy = Retry(
            total=3,                    # 重试3次
            backoff_factor=0.5,         # 重试延迟: 0.5s, 1s, 2s
            status_forcelist=[429, 500, 502, 503, 504],  # 对这些状态码重试
            allowed_methods=["POST", "GET"]
        )

        # 配置HTTP适配器
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=retry_strategy
        )

        # 挂载适配器
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        return session

    def _get_key_pool(self, chain: str) -> Optional[APIKeyPool]:
        """根据链名获取对应的KeyPool"""
        if chain not in EXPLORER_APIS:
            return None

        api_key_name = EXPLORER_APIS[chain].get('api_key_name', 'etherscan')
        key_pool = self.key_pools.get(api_key_name)

        if not key_pool:
            self.logger.warning(f"未配置 {api_key_name} 的API Key Pool")

        return key_pool

    def download_contract(self, address: ContractAddress, chain: str,
                         output_dir: Path, detect_proxy: bool = True,
                         _recursion_depth: int = 0) -> Tuple[bool, bool]:
        """
        下载合约源码或字节码,并自动检测和下载代理的实现合约

        Args:
            address: 合约地址
            chain: 链类型
            output_dir: 输出目录
            detect_proxy: 是否检测代理(默认True)
            _recursion_depth: 递归深度(内部使用,防止无限递归)

        Returns:
            (是否成功, 是否仅字节码)
        """
        # 防止无限递归(最多3层: Proxy -> Beacon -> Implementation)
        MAX_RECURSION_DEPTH = 3
        if _recursion_depth >= MAX_RECURSION_DEPTH:
            self.logger.warning(f"  代理递归深度超过限制({MAX_RECURSION_DEPTH}),停止检测")
            return False, False

        if chain not in EXPLORER_APIS:
            self.logger.warning(f"不支持的链类型: {chain}")
            return False, False

        api_config = EXPLORER_APIS[chain]

        # 获取该链对应的KeyPool
        key_pool = self._get_key_pool(chain)
        if not key_pool:
            self.logger.warning(f"  未配置API密钥用于链: {chain}")
            return False, False

        # 创建输出目录
        contract_dir = output_dir / f"{address.address}_{address.name or 'Unknown'}"
        contract_dir.mkdir(parents=True, exist_ok=True)

        # 下载源码(带重试)
        success = False
        is_bytecode_only = False
        proxy_info = None

        for attempt in range(API_RETRY_TIMES):
            try:
                # 从KeyPool获取一个API Key(自动限流)
                with key_pool.acquire_key() as api_key:
                    # 检查是否使用V1 API
                    use_v1 = api_config.get('use_v1', False)

                    # 调用API
                    source_code = self._fetch_source_code(
                        address.address,
                        api_config['api_url'],
                        api_config['chainid'],
                        api_key,
                        use_v1=use_v1
                    )

                    if not source_code:
                        # 合约未验证,尝试下载字节码
                        self.logger.info(f"  合约未验证,尝试下载字节码: {address.address[:10]}...")
                        bytecode_success = self._download_bytecode(address, chain, contract_dir)
                        if bytecode_success:
                            success = True
                            is_bytecode_only = True
                        break

                    # 保存源码
                    self._save_contract_files(source_code, contract_dir)
                    success = True
                    is_bytecode_only = False

                self.logger.info(f"  ✓ 下载成功: {address.address[:10]}...")
                break

            except Exception as e:
                self.logger.warning(f"  下载失败 (尝试 {attempt+1}/{API_RETRY_TIMES}): {e}")
                if attempt < API_RETRY_TIMES - 1:
                    time.sleep(API_RETRY_DELAY)

        # 如果下载成功且启用代理检测,检查是否为代理合约
        if success and detect_proxy:
            proxy_info = self.proxy_detector.detect_proxy(address.address, chain)

            if proxy_info and proxy_info.get('is_proxy'):
                impl_address = proxy_info.get('implementation')
                proxy_type = proxy_info.get('proxy_type')

                self.logger.info(f"  🔗 检测到{proxy_type}代理,实现合约: {impl_address[:10]}...")

                # 保存代理信息到metadata
                self._save_proxy_info(contract_dir, proxy_info)

                # 递归下载实现合约
                impl_contract_addr = ContractAddress(
                    address=impl_address,
                    name=f"{address.name or 'Unknown'}_Implementation",
                    chain=address.chain,
                    source="proxy_implementation"
                )

                self.logger.info(f"  ↳ 开始下载实现合约...")
                impl_success, impl_is_bytecode = self.download_contract(
                    impl_contract_addr,
                    chain,
                    output_dir,
                    detect_proxy=True,  # 实现合约也可能是代理(如Beacon)
                    _recursion_depth=_recursion_depth + 1
                )

                if impl_success:
                    self.logger.info(f"  ↳ 实现合约下载成功")
                else:
                    self.logger.warning(f"  ↳ 实现合约下载失败")

        return success, is_bytecode_only

    def _fetch_source_code(self, address: str, api_url: str, chainid: int, api_key: str, use_v1: bool = False) -> Optional[Dict]:
        """
        从API获取源码 (支持V1和V2 API)

        Returns:
            源码信息字典或None
        """
        if use_v1:
            # V1 API不需要chainid参数
            params = {
                'module': 'contract',
                'action': 'getsourcecode',
                'address': address,
                'apikey': api_key
            }
        else:
            # V2 API需要chainid参数
            params = {
                'chainid': chainid,
                'module': 'contract',
                'action': 'getsourcecode',
                'address': address,
                'apikey': api_key
            }

        response = requests.get(api_url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if data['status'] != '1' or not data['result']:
            return None

        result = data['result'][0]

        # 检查是否已验证
        if result['SourceCode'] == '':
            return None

        return result

    def _save_contract_files(self, source_code: Dict, output_dir: Path):
        """保存合约文件"""

        # 保存主源码
        source = source_code['SourceCode']

        # 处理多文件合约(JSON格式)
        if source.startswith('{{'):
            # 移除外层的大括号
            source = source[1:-1]
            sources = json.loads(source)

            # 保存所有源文件
            if 'sources' in sources:
                for file_path, file_data in sources['sources'].items():
                    file_output = output_dir / file_path.replace('/', '_')
                    with open(file_output, 'w', encoding='utf-8') as f:
                        f.write(file_data['content'])
        else:
            # 单文件合约
            contract_file = output_dir / f"{source_code['ContractName']}.sol"
            with open(contract_file, 'w', encoding='utf-8') as f:
                f.write(source)

        # 保存ABI
        if source_code['ABI'] != 'Contract source code not verified':
            abi_file = output_dir / 'abi.json'
            with open(abi_file, 'w', encoding='utf-8') as f:
                f.write(source_code['ABI'])

        # 保存元数据
        metadata = {
            'contract_name': source_code['ContractName'],
            'compiler_version': source_code['CompilerVersion'],
            'optimization': source_code['OptimizationUsed'] == '1',
            'runs': source_code['Runs'],
            'constructor_arguments': source_code.get('ConstructorArguments', ''),
            'evm_version': source_code.get('EVMVersion', ''),
            'library': source_code.get('Library', ''),
            'license_type': source_code.get('LicenseType', ''),
            'proxy': source_code.get('Proxy', '0') == '1',
            'implementation': source_code.get('Implementation', '')
        }

        metadata_file = output_dir / 'metadata.json'
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

    def _save_proxy_info(self, output_dir: Path, proxy_info: Dict[str, Any]):
        """
        保存代理信息到metadata.json

        Args:
            output_dir: 合约输出目录
            proxy_info: 代理信息字典
        """
        try:
            metadata_file = output_dir / 'metadata.json'

            # 读取现有metadata
            if metadata_file.exists():
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            else:
                metadata = {}

            # 添加代理信息
            metadata['proxy_detected'] = True
            metadata['proxy_type'] = proxy_info.get('proxy_type')
            metadata['implementation_address'] = proxy_info.get('implementation')

            if 'beacon' in proxy_info:
                metadata['beacon_address'] = proxy_info.get('beacon')

            # 保存更新后的metadata
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

        except Exception as e:
            self.logger.warning(f"  保存代理信息失败: {e}")

    def _download_bytecode(self, address: ContractAddress, chain: str, output_dir: Path) -> bool:
        """
        下载未验证合约的字节码(通过RPC,带重试机制)

        Args:
            address: 合约地址
            chain: 链类型
            output_dir: 输出目录

        Returns:
            是否成功
        """
        if chain not in EXPLORER_APIS:
            self.logger.warning(f"  不支持的链类型: {chain}")
            return False

        api_config = EXPLORER_APIS[chain]
        rpc_url = api_config.get('rpc_url')

        if not rpc_url:
            self.logger.warning(f"  未配置RPC URL用于链: {chain}")
            return False

        try:
            # 通过eth_getCode获取字节码
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_getCode",
                "params": [address.address, "latest"],
                "id": 1
            }

            # 使用带重试机制的session发送请求
            # ✅ 修复: 使用self.session替代直接的requests.post
            # 这样429错误会自动重试3次(0.5s, 1s, 2s延迟)
            response = self.session.post(rpc_url, json=payload, timeout=10)
            response.raise_for_status()

            data = response.json()

            if 'result' not in data:
                self.logger.warning(f"  RPC返回无效数据: {address.address}")
                return False

            bytecode = data['result']

            # 检查是否为空(0x或0x0)
            if not bytecode or bytecode == '0x' or bytecode == '0x0':
                self.logger.warning(f"  地址不是合约或已自毁: {address.address}")
                return False

            # 保存字节码
            bytecode_file = output_dir / 'bytecode.hex'
            with open(bytecode_file, 'w', encoding='utf-8') as f:
                f.write(bytecode)

            # 计算字节码大小
            bytecode_size = (len(bytecode) - 2) // 2  # 减去0x前缀,除以2得到字节数

            # 保存元数据
            metadata = {
                'address': address.address,
                'chain': chain,
                'verified': False,
                'bytecode_size': bytecode_size,
                'bytecode_file': 'bytecode.hex',
                'note': '合约未在区块浏览器上验证,仅包含字节码'
            }

            metadata_file = output_dir / 'metadata.json'
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2)

            self.logger.info(f"  ✓ 字节码下载成功: {address.address[:10]}... (大小: {bytecode_size} bytes)")
            return True

        except requests.exceptions.RetryError as e:
            # 重试耗尽后的异常
            self.logger.error(f"  下载字节码失败(重试3次后仍失败): {e}")
            return False
        except requests.exceptions.HTTPError as e:
            # HTTP错误(如404, 500等,不在重试列表中)
            self.logger.error(f"  下载字节码失败(HTTP错误): {e}")
            return False
        except Exception as e:
            self.logger.error(f"  下载字节码失败: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """获取所有KeyPool的统计信息"""
        all_stats = {}
        for key_name, key_pool in self.key_pools.items():
            all_stats[key_name] = key_pool.get_stats()
        return all_stats


# ============================================================================
# 主控制器
# ============================================================================

class ContractExtractor:
    """主控制器 - 协调各个模块"""

    def __init__(self, test_dir: Path, output_dir: Path,
                 api_keys: Optional[Dict[str, str]] = None,
                 diff_enabled: bool = False,
                 force_overwrite: bool = False):
        self.test_dir = test_dir
        self.output_dir = output_dir

        # 使用传入的api_keys或默认配置
        self.api_keys = api_keys or DEFAULT_API_KEYS

        # diff 行为控制
        self.diff_enabled = diff_enabled
        self.force_overwrite = force_overwrite
        self.diff_results: List[Dict[str, Any]] = []

        # 统计信息
        self.summary = ExecutionSummary()

        # 日志 - 必须先初始化
        self.logger = logging.getLogger(__name__ + '.ContractExtractor')

        # 初始化各模块
        self.static_analyzer = StaticAnalyzer()
        self.dynamic_analyzer = DynamicAnalyzer()
        self.source_downloader = SourceDownloader(self.api_keys)

        # 初始化OnChainDataFetcher
        self.onchain_fetcher = None
        if ONCHAIN_FETCHER_AVAILABLE:
            try:
                config_path = Path(__file__).parent.parent.parent / "config" / "api_keys.json"
                if config_path.exists():
                    self.onchain_fetcher = OnChainDataFetcher.from_config(str(config_path))
                    self.logger.info("OnChainDataFetcher初始化成功")
                else:
                    self.logger.warning(f"config/api_keys.json不存在,跳过链上数据补全")
            except Exception as e:
                self.logger.warning(f"OnChainDataFetcher初始化失败: {e}")

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 错误日志文件
        self.error_log = self.output_dir / 'error.log'
        self.unverified_file = self.output_dir / 'unverified.json'
        self.summary_file = self.output_dir / 'summary.json'

    def extract_all(self, date_filters: Optional[List[str]] = None,
                    protocol_filter: Optional[str] = None,
                    limit: Optional[int] = None):
        """
        提取所有脚本的合约

        Args:
            date_filters: 日期过滤器列表,如 ["2025-08","2025-09"]
            protocol_filter: 协议名过滤器,如 "ETHFIN_exp"
            limit: 最多处理的脚本数量
        """
        self.logger.info("=" * 80)
        self.logger.info("开始提取DeFi攻击合约")
        self.logger.info("=" * 80)

        # 查找所有测试脚本
        scripts = self._find_all_scripts(date_filters, protocol_filter)

        if limit is not None:
            scripts = scripts[:max(limit, 0)]

        self.summary.total_scripts = len(scripts)

        self.logger.info(f"找到 {len(scripts)} 个测试脚本")

        # 处理每个脚本
        unverified_contracts = []

        for i, script in enumerate(scripts, 1):
            self.logger.info(f"\n[{i}/{len(scripts)}] 处理: {script.date_dir}/{script.name}")
            script_start = time.perf_counter()

            try:
                success = self._process_script(script, unverified_contracts)
                if success:
                    self.summary.successful_scripts += 1
                else:
                    self.summary.failed_scripts += 1
            except Exception as e:
                error_msg = f"处理脚本失败 {script.name}: {e}"
                self.logger.error(error_msg)
                self.summary.errors.append(error_msg)
                self.summary.failed_scripts += 1
                self._log_error(error_msg)
            finally:
                elapsed = time.perf_counter() - script_start
                self.logger.info(f"  {script.name} 总耗时: {elapsed:.2f}s")

        # 保存未验证合约列表
        if unverified_contracts:
            with open(self.unverified_file, 'w') as f:
                json.dump(unverified_contracts, f, indent=2)

        # 保存执行摘要
        self._save_summary()

        # 打印统计
        self._print_summary()
        self._print_diff_report()

    def _find_all_scripts(self, date_filters: Optional[List[str]] = None,
                         protocol_filter: Optional[str] = None) -> List[ExploitScript]:
        """
        查找所有测试脚本

        Args:
            date_filters: 日期过滤器列表
            protocol_filter: 协议名过滤器
        """
        scripts = []

        # 遍历所有日期目录
        for date_dir in sorted(self.test_dir.iterdir()):
            if not date_dir.is_dir():
                continue

            # 匹配 YYYY-MM 格式
            if not re.match(r'\d{4}-\d{2}', date_dir.name):
                continue

            # 应用日期过滤器
            if date_filters and not any(date_dir.name.startswith(f) for f in date_filters):
                continue

            # 查找该目录下的所有.sol文件
            for sol_file in date_dir.glob('*.sol'):
                script_name = sol_file.stem

                # 应用协议过滤器
                if protocol_filter and script_name != protocol_filter:
                    continue

                script = ExploitScript(
                    file_path=sol_file,
                    name=script_name,
                    date_dir=date_dir.name
                )
                scripts.append(script)

        return scripts

    def _process_script(self, script: ExploitScript,
                       unverified_contracts: List[Dict]) -> bool:
        """
        处理单个脚本

        Returns:
            是否成功
        """
        # 1. 静态分析
        t0 = time.perf_counter()
        static_addresses, chain = self.static_analyzer.analyze_script(script)
        self.logger.info(f"  静态分析耗时: {time.perf_counter() - t0:.2f}s, 地址数: {len(static_addresses)}")
        script.chain = chain or script.chain

        # 2. 动态分析
        dynamic_addresses = []
        if self.dynamic_analyzer:
            t1 = time.perf_counter()
            dynamic_addresses = self.dynamic_analyzer.analyze_script(script)
            self.logger.info(f"  动态分析耗时: {time.perf_counter() - t1:.2f}s, 地址数: {len(dynamic_addresses)}")
        else:
            self.logger.info("  动态分析已禁用")

        # 3. 合并地址
        t2 = time.perf_counter()
        all_addresses = self._merge_addresses(static_addresses, dynamic_addresses, script.chain)
        self.logger.info(f"  地址合并耗时: {time.perf_counter() - t2:.2f}s")

        if not all_addresses:
            self.logger.warning("  未提取到任何地址")
            return False

        self.logger.info(f"  共提取到 {len(all_addresses)} 个唯一地址")
        self.summary.total_addresses += len(all_addresses)

        # 4. 创建输出目录
        script_output_dir = self.output_dir / script.date_dir / script.name
        script_output_dir.mkdir(parents=True, exist_ok=True)

        existing_addresses = self._load_existing_addresses(script_output_dir)
        if self.diff_enabled:
            diff_info = self._calculate_diff(existing_addresses or [], all_addresses)
            self._record_diff(script, script_output_dir, diff_info, existing_addresses is not None)

            if existing_addresses and not self.force_overwrite:
                self.logger.info("  diff模式：已展示差异，如需覆盖请增加 --force")
                return True

        # 5. 补全链上数据
        if script.chain:
            t3 = time.perf_counter()
            all_addresses = self._enrich_with_onchain_data(all_addresses, script.chain)
            self.logger.info(f"  链上数据补全耗时: {time.perf_counter() - t3:.2f}s")

        # 6. 保存地址列表
        t4 = time.perf_counter()
        self._save_addresses(all_addresses, script_output_dir / 'addresses.json')
        self.logger.info(f"  保存地址耗时: {time.perf_counter() - t4:.2f}s")

        # 7. 下载源码（同时收集代理检测到的实现合约地址）
        implementation_addresses = []
        if script.chain:
            t5 = time.perf_counter()
            implementation_addresses = self._download_sources_with_impl_collection(
                all_addresses, script.chain,
                script_output_dir, unverified_contracts
            )
            self.logger.info(f"  源码下载耗时: {time.perf_counter() - t5:.2f}s")

            # 8. 如果发现新的实现合约地址，更新addresses.json
            if implementation_addresses:
                self.logger.info(f"  检测到 {len(implementation_addresses)} 个实现合约，更新addresses.json")
                # 合并实现合约地址到all_addresses
                existing_addrs = {addr.address.lower() for addr in all_addresses}
                for impl_addr in implementation_addresses:
                    if impl_addr.address.lower() not in existing_addrs:
                        all_addresses.append(impl_addr)
                        existing_addrs.add(impl_addr.address.lower())
                # 重新保存addresses.json
                self._save_addresses(all_addresses, script_output_dir / 'addresses.json')
        else:
            self.logger.warning("  未识别链类型,跳过源码下载")

        return True

    def _merge_addresses(self, static: List[ContractAddress],
                        dynamic: List[ContractAddress],
                        chain: Optional[str]) -> List[ContractAddress]:
        """合并静态和动态地址，并强制传播链类型"""
        # 使用字典去重,保留更多信息
        merged = {}

        for addr in static + dynamic:
            key = addr.address.lower()
            if key in merged:
                # 合并信息
                existing = merged[key]
                if not existing.name and addr.name:
                    existing.name = addr.name
                if not existing.chain and addr.chain:
                    existing.chain = addr.chain
            else:
                if not addr.chain and chain:
                    addr.chain = chain
                merged[key] = addr

        # 强制传播链类型到所有地址（确保没有遗漏）
        if chain:
            for addr in merged.values():
                if not addr.chain:
                    addr.chain = chain

        return list(merged.values())

    def _enrich_with_onchain_data(self, addresses: List[ContractAddress], chain: str) -> List[ContractAddress]:
        """
        使用OnChainDataFetcher补全链上信息

        为每个地址添加:
        - onchain_name: 从链上获取的合约名称
        - symbol: ERC20 token symbol
        - decimals: ERC20 decimals
        - is_erc20: 是否为ERC20
        - semantic_type: 语义类型
        - aliases: 别名列表
        """
        if not self.onchain_fetcher:
            self.logger.debug("  OnChainDataFetcher不可用,跳过链上数据补全")
            return addresses

        if not addresses:
            return addresses

        self.logger.info(f"  开始补全链上数据 ({len(addresses)}个地址)...")

        try:
            # 提取地址列表
            address_list = [addr.address for addr in addresses]

            # 批量获取链上数据
            onchain_data = asyncio.run(
                self.onchain_fetcher.batch_fetch_contracts(address_list, chain=chain)
            )

            # 补全每个ContractAddress对象
            enriched_count = 0
            for addr in addresses:
                addr_lower = addr.address.lower()
                if addr_lower in onchain_data:
                    info = onchain_data[addr_lower]

                    # 跳过错误的结果
                    if 'error' in info:
                        continue

                    # 补全字段
                    addr.onchain_name = info.get('contract_name')
                    addr.symbol = info.get('symbol')
                    addr.decimals = info.get('decimals')
                    addr.is_erc20 = info.get('is_erc20')
                    addr.semantic_type = info.get('semantic_type')

                    # 构建别名列表
                    aliases = []
                    if addr.symbol:
                        aliases.append(addr.symbol)
                    if addr.name and addr.name not in aliases:
                        aliases.append(addr.name)
                    if addr.onchain_name and addr.onchain_name not in aliases:
                        aliases.append(addr.onchain_name)

                    # 添加常见变体
                    if addr.symbol:
                        # 添加小写和大写变体
                        aliases.extend([addr.symbol.lower(), addr.symbol.upper()])
                        # 添加I前缀变体(接口命名约定)
                        if not addr.symbol.startswith('I'):
                            aliases.append(f'I{addr.symbol}')

                    # 去重
                    addr.aliases = list(dict.fromkeys(aliases))  # 保持顺序的去重

                    enriched_count += 1

            self.logger.info(f"  ✓ 链上数据补全完成: {enriched_count}/{len(addresses)} 个地址")

            return addresses

        except Exception as e:
            self.logger.warning(f"  链上数据补全失败: {e}")
            self.logger.debug(f"  错误详情: {e}", exc_info=True)
            return addresses

    def _save_addresses(self, addresses: List[ContractAddress], output_file: Path):
        """保存地址列表"""
        data = [asdict(addr) for addr in addresses]
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _download_sources(self, addresses: List[ContractAddress],
                         chain: str, output_dir: Path,
                         unverified_contracts: List[Dict]):
        """下载所有地址的源码(并发下载,带预检查优化)"""
        if not addresses:
            return

        # 获取该链的KeyPool,确定并发线程数
        key_pool = self.source_downloader._get_key_pool(chain)
        if not key_pool:
            self.logger.warning(f"  未配置API Key,跳过源码下载")
            return

        # 获取RPC URL用于批量预检查
        rpc_url = EXPLORER_APIS[chain].get('rpc_url') if chain in EXPLORER_APIS else None

        # 批量预检查: 先快速检查哪些地址是真实合约 (避免浪费时间下载无效地址)
        valid_contract_addrs = set()
        if rpc_url:
            address_list = [addr.address for addr in addresses]
            valid_contract_addrs = batch_check_contracts_exist(address_list, rpc_url, timeout=3, max_workers=10)

            # 过滤出有效的合约
            if valid_contract_addrs:
                original_count = len(addresses)
                addresses = [addr for addr in addresses if addr.address.lower() in valid_contract_addrs]
                filtered_count = original_count - len(addresses)
                if filtered_count > 0:
                    self.logger.info(f"  已过滤 {filtered_count} 个无效地址,剩余 {len(addresses)} 个待下载")
        else:
            self.logger.warning(f"  未配置RPC URL,跳过预检查")

        if not addresses:
            self.logger.info(f"  预检查后无有效合约需要下载")
            return

        # 使用key数量作为并发线程数(每个线程使用一个key)
        max_workers = len(key_pool.keys)
        self.logger.info(f"  开始下载源码 (链: {chain}, 并发数: {max_workers})")

        # 使用线程锁保护共享数据
        stats_lock = threading.Lock()

        def download_one(addr: ContractAddress) -> bool:
            """下载单个合约(供线程池使用)"""
            success, is_bytecode_only = self.source_downloader.download_contract(addr, chain, output_dir)

            # 更新统计信息(需要加锁)
            with stats_lock:
                if success:
                    if is_bytecode_only:
                        self.summary.bytecode_only_contracts += 1
                    else:
                        self.summary.verified_contracts += 1
                else:
                    self.summary.unverified_contracts += 1
                    unverified_contracts.append({
                        'address': addr.address,
                        'chain': chain,
                        'name': addr.name
                    })

            return success

        # 使用线程池并发下载
        download_start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有下载任务
            futures = {
                executor.submit(download_one, addr): addr
                for addr in addresses
            }

            # 等待所有任务完成
            for future in as_completed(futures):
                addr = futures[future]
                try:
                    success = future.result()
                except Exception as e:
                    self.logger.error(f"  下载 {addr.address} 时发生异常: {e}")
                    with stats_lock:
                        self.summary.unverified_contracts += 1
        total_download_time = time.perf_counter() - download_start
        self.logger.info(f"  源码下载完成, 耗时 {total_download_time:.2f}s")

    def _download_sources_with_impl_collection(self, addresses: List[ContractAddress],
                                               chain: str, output_dir: Path,
                                               unverified_contracts: List[Dict]) -> List[ContractAddress]:
        """
        下载所有地址的源码，并收集代理检测到的实现合约地址

        Returns:
            检测到的实现合约地址列表
        """
        if not addresses:
            return []

        # 先执行标准下载
        self._download_sources(addresses, chain, output_dir, unverified_contracts)

        # 扫描输出目录中的metadata.json文件，查找代理合约的实现地址
        implementation_addresses = []
        seen_impl_addrs = set()

        for item in output_dir.iterdir():
            if not item.is_dir():
                continue

            metadata_file = item / 'metadata.json'
            if not metadata_file.exists():
                continue

            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                # 检查是否检测到代理
                if metadata.get('proxy_detected') or metadata.get('proxy'):
                    impl_address = metadata.get('implementation_address') or metadata.get('implementation')
                    if impl_address and isinstance(impl_address, str) and impl_address.startswith('0x'):
                        impl_address_lower = impl_address.lower()
                        if impl_address_lower not in seen_impl_addrs:
                            seen_impl_addrs.add(impl_address_lower)

                            # 从目录名推断代理合约名称
                            proxy_name = item.name.split('_', 1)[1] if '_' in item.name else 'Unknown'
                            if proxy_name.endswith('_Implementation'):
                                proxy_name = proxy_name[:-15]  # 移除 _Implementation 后缀

                            impl_contract = ContractAddress(
                                address=impl_address,
                                name=f"{proxy_name}_Implementation",
                                chain=chain,
                                source="proxy_implementation"
                            )
                            implementation_addresses.append(impl_contract)
                            self.logger.debug(f"  收集到实现合约: {impl_address[:10]}... ({proxy_name})")

            except Exception as e:
                self.logger.debug(f"  读取 {metadata_file} 时出错: {e}")

        return implementation_addresses

    def _load_existing_addresses(self, script_output_dir: Path) -> Optional[List[Dict]]:
        """读取现有的 addresses.json"""
        addresses_file = script_output_dir / 'addresses.json'
        if not addresses_file.exists():
            return None
        try:
            with open(addresses_file, 'r') as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            self.logger.warning(f"  addresses.json 格式异常: {addresses_file}")
            return None
        except Exception as e:
            self.logger.warning(f"  读取现有 addresses.json 失败: {e}")
            return None

    def _calculate_diff(self, old_list: List[Dict], new_list: List[ContractAddress]) -> Dict[str, Any]:
        """计算新旧数据的差异"""
        new_dicts = [asdict(addr) for addr in new_list]

        old_map = self._addresses_to_map(old_list)
        new_map = self._addresses_to_map(new_dicts)

        added = []
        for entry in new_dicts:
            address = entry.get('address')
            if not isinstance(address, str):
                continue
            if address.lower() not in old_map:
                added.append(entry)

        removed = []
        for entry in old_list:
            address = entry.get('address')
            if not isinstance(address, str):
                continue
            if address.lower() not in new_map:
                removed.append(entry)

        changed = []
        for addr_lower, old_entry in old_map.items():
            if addr_lower not in new_map:
                continue
            new_entry = new_map[addr_lower]
            field_changes = {}
            for field in ('name', 'chain', 'source', 'context'):
                if old_entry.get(field) != new_entry.get(field):
                    field_changes[field] = {
                        'old': old_entry.get(field),
                        'new': new_entry.get(field)
                    }
            if field_changes:
                changed.append({
                    'address': new_entry.get('address', old_entry.get('address')),
                    'changes': field_changes
                })

        return {
            'added': added,
            'removed': removed,
            'changed': changed
        }

    def _addresses_to_map(self, entries: List[Dict]) -> Dict[str, Dict]:
        mapping: Dict[str, Dict] = {}
        for entry in entries:
            address = entry.get('address')
            if not isinstance(address, str):
                continue
            mapping[address.lower()] = entry
        return mapping

    def _record_diff(self, script: ExploitScript, script_output_dir: Path,
                     diff_info: Dict[str, Any], had_baseline: bool):
        """输出并记录单个脚本的差异"""
        added = diff_info.get('added', [])
        removed = diff_info.get('removed', [])
        changed = diff_info.get('changed', [])

        summary = f"+{len(added)} -{len(removed)} ~{len(changed)}"
        if not had_baseline:
            summary += " (首次生成基线)"
        self.logger.info(f"  diff 结果: {summary}")

        if added:
            for entry in added:
                self.logger.info(f"    + {entry.get('address')} ({entry.get('name') or '-'})")
        if removed:
            for entry in removed:
                self.logger.info(f"    - {entry.get('address')} ({entry.get('name') or '-'})")
        if changed:
            for entry in changed:
                changes_desc = ", ".join(
                    f"{field}: {detail['old']} -> {detail['new']}"
                    for field, detail in entry['changes'].items()
                )
                self.logger.info(f"    ~ {entry['address']}: {changes_desc}")

        self.diff_results.append({
            'script': script.name,
            'date_dir': script.date_dir,
            'path': str(script_output_dir),
            'added': added,
            'removed': removed,
            'changed': changed
        })

    def _print_diff_report(self):
        """打印 diff 汇总报告"""
        if not self.diff_enabled:
            return

        self.logger.info("\n" + "=" * 80)
        self.logger.info("Diff 报告")
        self.logger.info("=" * 80)

        if not self.diff_results:
            self.logger.info("未生成 diff 结果")
            return

        for item in self.diff_results:
            stats = f"+{len(item['added'])} -{len(item['removed'])} ~{len(item['changed'])}"
            self.logger.info(f"{item['date_dir']}/{item['script']}: {stats}")
            if item['added']:
                for entry in item['added']:
                    self.logger.info(f"  + {entry.get('address')} ({entry.get('name') or '-'})")
            if item['removed']:
                for entry in item['removed']:
                    self.logger.info(f"  - {entry.get('address')} ({entry.get('name') or '-'})")
            if item['changed']:
                for entry in item['changed']:
                    changes_desc = ", ".join(
                        f"{field}: {detail['old']} -> {detail['new']}"
                        for field, detail in entry['changes'].items()
                    )
                    self.logger.info(f"  ~ {entry['address']}: {changes_desc}")


    def _log_error(self, message: str):
        """记录错误到日志文件"""
        with open(self.error_log, 'a') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

    def _save_summary(self):
        """保存执行摘要"""
        # 获取KeyPool统计信息
        key_stats = self.source_downloader.get_stats()
        total_api_calls = sum(stats['total_calls'] for stats in key_stats.values())

        self.summary.api_calls = total_api_calls

        # 保存完整摘要(包含Key统计)
        summary_with_stats = asdict(self.summary)
        summary_with_stats['key_pool_stats'] = key_stats

        with open(self.summary_file, 'w') as f:
            json.dump(summary_with_stats, f, indent=2)

    def _print_summary(self):
        """打印执行摘要"""
        self.logger.info("\n" + "=" * 80)
        self.logger.info("执行摘要")
        self.logger.info("=" * 80)
        self.logger.info(f"总脚本数:        {self.summary.total_scripts}")
        self.logger.info(f"成功:            {self.summary.successful_scripts}")
        self.logger.info(f"失败:            {self.summary.failed_scripts}")
        self.logger.info(f"总地址数:        {self.summary.total_addresses}")
        self.logger.info(f"已验证合约:      {self.summary.verified_contracts}")
        self.logger.info(f"未验证合约:      {self.summary.unverified_contracts}")
        self.logger.info(f"  └─ 仅字节码:   {self.summary.bytecode_only_contracts}")
        self.logger.info(f"API调用次数:     {self.summary.api_calls}")

        # 打印KeyPool统计
        key_stats = self.source_downloader.get_stats()
        if key_stats:
            self.logger.info(f"\nAPI Key并发统计:")
            for key_name, stats in key_stats.items():
                self.logger.info(f"  {key_name}:")
                self.logger.info(f"    Key数量: {stats['key_count']}")
                self.logger.info(f"    总调用: {stats['total_calls']}")
                # 显示每个key的负载均衡情况
                per_key = stats['per_key_calls']
                if per_key:
                    call_counts = list(per_key.values())
                    self.logger.info(f"    负载均衡: 最小={min(call_counts)}, 最大={max(call_counts)}, 平均={sum(call_counts)/len(call_counts):.1f}")

        self.logger.info(f"\n输出目录:        {self.output_dir}")
        if self.summary.errors:
            self.logger.info(f"错误数:          {len(self.summary.errors)}")
            self.logger.info(f"错误日志:        {self.error_log}")
        self.logger.info("=" * 80)


# ============================================================================
# 命令行接口
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='DeFi攻击合约源码提取工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 处理2025-08目录
  python extract_contracts.py --filter 2025-08

  # 处理特定协议
  python extract_contracts.py --protocol ETHFIN_exp

  # 结合日期过滤和协议过滤
  python extract_contracts.py --filter 2024-01 --protocol Freedom_exp

  # 处理所有脚本
  python extract_contracts.py

  # 使用API Key
  python extract_contracts.py --api-key YOUR_API_KEY

  # 同时处理多个目录
  python extract_contracts.py --filter 2025-08 --filter 2025-09

  # 只做静态分析(不运行测试)
  python extract_contracts.py --static-only

  # 对比已有结果但不覆盖
  python extract_contracts.py --filter 2024-01 --diff

  # 对比并覆盖
  python extract_contracts.py --filter 2024-01 --diff --force

  # 强制重新提取特定协议
  python extract_contracts.py --protocol ETHFIN_exp --force
        """
    )

    parser.add_argument(
        '--test-dir',
        type=Path,
        default=DEFAULT_TEST_DIR,
        help='测试脚本目录 (默认: 项目根目录下的src/test)'
    )

    parser.add_argument(
        '--output-dir',
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help='输出目录 (默认: 项目根目录下的extracted_contracts)'
    )

    parser.add_argument(
        '--filter',
        dest='filters',
        action='append',
        help='日期过滤器,可重复使用或用逗号分隔多个值,如 "2025-08,2025-09"(默认: 处理所有)'
    )

    parser.add_argument(
        '--protocol',
        type=str,
        help='协议名过滤器,只处理匹配的协议,如 "ETHFIN_exp"'
    )

    parser.add_argument(
        '--api-key',
        type=str,
        help='(可选) 覆盖默认的API Key配置'
    )

    parser.add_argument(
        '--static-only',
        action='store_true',
        help='只做静态分析,不运行forge test'
    )

    parser.add_argument(
        '--diff',
        action='store_true',
        help='比较新旧结果，输出差异（默认不覆盖已有文件）'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='与 --diff 搭配时强制覆盖输出目录，仍会打印差异'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='启用调试日志'
    )

    parser.add_argument(
        '--log-file',
        type=Path,
        default=DEFAULT_LOG_FILE,
        help=f'日志输出文件 (默认: {DEFAULT_LOG_FILE})'
    )

    parser.add_argument(
        '--limit',
        type=int,
        help='限制处理的脚本数量, 例如 --limit 1'
    )

    args = parser.parse_args()

    # 设置日志级别
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 日志文件
    if args.log_file:
        log_file_path = args.log_file
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logging.getLogger().addHandler(file_handler)
        logger.info(f"日志写入: {log_file_path}")

    # API Keys已硬编码在DEFAULT_API_KEYS中
    # 如果用户提供了api-key参数,可以覆盖Etherscan key
    api_keys = DEFAULT_API_KEYS.copy()
    if args.api_key:
        api_keys['etherscan'] = args.api_key
        logger.info(f"使用自定义Etherscan API Key")
    else:
        logger.info("使用硬编码的API Keys配置")

    # 创建提取器
    extractor = ContractExtractor(
        test_dir=args.test_dir,
        output_dir=args.output_dir,
        api_keys=api_keys,
        diff_enabled=args.diff,
        force_overwrite=args.force
    )

    # 如果只做静态分析,禁用动态分析器
    if args.static_only:
        extractor.dynamic_analyzer = None
        logger.info("只执行静态分析模式")

    # 解析日期过滤器
    date_filters = None
    if args.filters:
        parsed_filters = []
        for value in args.filters:
            for item in value.split(','):
                item = item.strip()
                if item:
                    parsed_filters.append(item)
        if parsed_filters:
            date_filters = sorted(set(parsed_filters))

    # 执行提取
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit 必须为正整数")

    # 执行提取
    try:
        extractor.extract_all(
            date_filters=date_filters,
            protocol_filter=args.protocol,
            limit=args.limit
        )
    except KeyboardInterrupt:
        logger.info("\n\n用户中断,正在保存进度...")
        extractor._save_summary()
        logger.info("进度已保存")


if __name__ == '__main__':
    main()
