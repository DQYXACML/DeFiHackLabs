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
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import logging
import tempfile
import shutil
from contextlib import contextmanager

# ============================================================================
# 配置
# ============================================================================

# API Keys配置 (写死在脚本中)
# 注意: Etherscan API V2统一支持多个网络,包括BSC!
DEFAULT_API_KEYS = {
    "etherscan": "2DTB79CHTEJ6PEDCTEINC8GV3IHUXHGP9A",  # 用于 Ethereum, Base, Optimism, Blast, Linea, BSC等
    # BSC现在也使用Etherscan API V2,不需要单独的Key了!
    # 其他独立网络的Key可以在这里添加:
    # "arbiscan": "YOUR_ARBISCAN_KEY",
    # "polygonscan": "YOUR_POLYGONSCAN_KEY",
}

# 区块浏览器API配置 (V2)
# 注意: Etherscan已迁移到V2 API,需要chainid参数
EXPLORER_APIS = {
    "mainnet": {
        "name": "Etherscan",
        "api_url": "https://api.etherscan.io/v2/api",
        "web_url": "https://etherscan.io",
        "chainid": 1,
        "api_key_name": "etherscan"  # 使用哪个API Key
    },
    "arbitrum": {
        "name": "Arbiscan",
        "api_url": "https://api.etherscan.io/v2/api",  # Arbitrum现已统一至Etherscan V2端点
        "web_url": "https://arbiscan.io",
        "chainid": 42161,
        "api_key_name": "etherscan"
    },
    "bsc": {
        "name": "BscScan",
        "api_url": "https://api.etherscan.io/v2/api",  # BSC通过Etherscan统一端点访问
        "web_url": "https://bscscan.com",
        "chainid": 56,
        "api_key_name": "etherscan"  # BSC使用Etherscan Key!
    },
    "base": {
        "name": "BaseScan",
        "api_url": "https://api.basescan.org/v2/api",
        "web_url": "https://basescan.org",
        "chainid": 8453,
        "api_key_name": "etherscan"  # Base可以用Etherscan Key
    },
    "optimism": {
        "name": "Optimism Etherscan",
        "api_url": "https://api-optimistic.etherscan.io/v2/api",
        "web_url": "https://optimistic.etherscan.io",
        "chainid": 10,
        "api_key_name": "etherscan"  # Optimism可以用Etherscan Key
    },
    "blast": {
        "name": "BlastScan",
        "api_url": "https://api.blastscan.io/v2/api",
        "web_url": "https://blastscan.io",
        "chainid": 81457,
        "api_key_name": "etherscan"  # Blast可以用Etherscan Key
    },
    "polygon": {
        "name": "PolygonScan",
        "api_url": "https://api.polygonscan.com/v2/api",
        "web_url": "https://polygonscan.com",
        "chainid": 137,
        "api_key_name": "polygonscan"
    },
    "avalanche": {
        "name": "SnowTrace",
        "api_url": "https://api.snowtrace.io/v2/api",
        "web_url": "https://snowtrace.io",
        "chainid": 43114,
        "api_key_name": "snowtrace"
    },
    "fantom": {
        "name": "FTMScan",
        "api_url": "https://api.ftmscan.com/v2/api",
        "web_url": "https://ftmscan.com",
        "chainid": 250,
        "api_key_name": "ftmscan"
    },
}

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
        # address constant NAME = 0x...
        re.compile(r'address\s+(?:constant\s+)?(?:public\s+)?(\w+)\s*=\s*(0x[a-fA-F0-9]{40})'),
        # IERC20 constant token = IERC20(0x...)
        re.compile(r'(\w+)\s+constant\s+(\w+)\s*=\s*\w+\((0x[a-fA-F0-9]{40})\)'),
        # Interface(0x...)
        re.compile(r'\w+\((0x[a-fA-F0-9]{40})\)'),
    ]

    # 注释中的关键字
    COMMENT_KEYWORDS = [
        'Attacker',
        'Attack Contract',
        'Vulnerable Contract',
        'Victim'
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
        """从代码中提取地址"""
        addresses = []

        # 提取address constant定义
        for pattern in self.ADDRESS_PATTERNS:
            matches = pattern.finditer(content)
            for match in matches:
                groups = match.groups()
                # 查找地址
                addr = None
                name = None
                for g in groups:
                    if g and g.startswith('0x') and len(g) == 42:
                        addr = g
                    elif g and not g.startswith('0x'):
                        name = g

                if addr:
                    addresses.append(ContractAddress(
                        address=addr,
                        name=name,
                        source='static',
                        context=match.group(0)
                    ))

        return addresses

    def _extract_chain(self, content: str) -> Optional[str]:
        """提取链类型"""
        match = re.search(r'createSelectFork\("(\w+)"', content)
        if match:
            return match.group(1)
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

    # 匹配CALL指令的地址
    CALL_PATTERN = re.compile(r'\[(\d+)\]\s+(\w+)::\w+.*?@(0x[a-fA-F0-9]{40})')
    # 匹配合约创建
    CREATE_PATTERN = re.compile(r'→ new.*?@(0x[a-fA-F0-9]{40})')

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.DynamicAnalyzer')
        self.project_root = PROJECT_ROOT

    def analyze_script(self, script: ExploitScript) -> List[ContractAddress]:
        """
        运行forge test并提取调用的所有合约

        Returns:
            地址列表
        """
        self.logger.info(f"动态分析: {script.name}")

        try:
            # 运行forge test
            result = self._run_forge_test(script.file_path)

            if result is None:
                self.logger.warning(f"  测试运行失败,跳过动态分析")
                return []

            # 解析trace提取地址
            addresses = self._parse_trace(result)

            self.logger.info(f"  动态提取到 {len(addresses)} 个地址")
            return addresses

        except Exception as e:
            self.logger.error(f"动态分析失败: {e}")
            return []

    def _run_forge_test(self, test_file: Path, timeout: int = 300) -> Optional[str]:
        """
        运行forge test

        Args:
            test_file: 测试文件路径
            timeout: 超时时间(秒)

        Returns:
            测试输出或None(如果失败)
        """
        try:
            with self._isolated_project(test_file) as (temp_root, match_path):
                cmd = [
                    'forge', 'test',
                    '--match-path', str(match_path),
                    '-vvvv'  # 最详细的输出
                ]

                self.logger.debug(f"  执行命令: {' '.join(cmd)}")
                self.logger.debug(f"  工作目录: {temp_root}")

                result = subprocess.run(
                    cmd,
                    cwd=temp_root,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )

            # 即使测试失败,也可能有trace输出
            output = result.stdout + result.stderr

            if result.returncode != 0:
                self.logger.warning(f"  测试返回非零状态码: {result.returncode}")
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

        # 提取CALL调用的合约
        for match in self.CALL_PATTERN.finditer(output):
            depth = match.group(1)
            call_type = match.group(2)
            address = match.group(3)

            if address.lower() not in seen:
                seen.add(address.lower())
                addresses.append(ContractAddress(
                    address=address,
                    source='dynamic',
                    context=f'{call_type} at depth {depth}'
                ))

        # 提取CREATE创建的合约
        for match in self.CREATE_PATTERN.finditer(output):
            address = match.group(1)
            if address.lower() not in seen:
                seen.add(address.lower())
                addresses.append(ContractAddress(
                    address=address,
                    source='dynamic',
                    context='contract created'
                ))

        return addresses


# ============================================================================
# 源码下载模块
# ============================================================================

class SourceDownloader:
    """源码下载器 - 从区块浏览器下载合约源码"""

    def __init__(self, api_keys: Optional[Dict[str, str]] = None):
        # 使用传入的API Keys,如果没有则使用默认配置
        self.api_keys = api_keys or DEFAULT_API_KEYS
        self.logger = logging.getLogger(__name__ + '.SourceDownloader')
        self.last_api_call = 0
        self.api_call_count = 0

    def _get_api_key_for_chain(self, chain: str) -> str:
        """根据链名获取对应的API Key"""
        if chain not in EXPLORER_APIS:
            return ""

        api_key_name = EXPLORER_APIS[chain].get('api_key_name', 'etherscan')
        api_key = self.api_keys.get(api_key_name, "")

        if not api_key:
            self.logger.warning(f"未配置 {api_key_name} 的API Key")

        return api_key

    def _rate_limit(self):
        """API限流"""
        now = time.time()
        elapsed = now - self.last_api_call

        # 每秒最多5次调用
        if elapsed < 1.0 / API_RATE_LIMIT:
            sleep_time = (1.0 / API_RATE_LIMIT) - elapsed
            time.sleep(sleep_time)

        self.last_api_call = time.time()
        self.api_call_count += 1

    def download_contract(self, address: ContractAddress, chain: str,
                         output_dir: Path) -> bool:
        """
        下载合约源码

        Args:
            address: 合约地址
            chain: 链类型
            output_dir: 输出目录

        Returns:
            是否成功
        """
        if chain not in EXPLORER_APIS:
            self.logger.warning(f"不支持的链类型: {chain}")
            return False

        api_config = EXPLORER_APIS[chain]

        # 创建输出目录
        contract_dir = output_dir / f"{address.address}_{address.name or 'Unknown'}"
        contract_dir.mkdir(parents=True, exist_ok=True)

        # 下载源码
        for attempt in range(API_RETRY_TIMES):
            try:
                self._rate_limit()

                # 获取该链对应的API密钥
                api_key = self._get_api_key_for_chain(chain)

                if not api_key:
                    self.logger.warning(f"  未配置API密钥用于链: {chain}")
                    return False

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
                    self.logger.warning(f"  合约未验证: {address.address}")
                    return False

                # 保存源码
                self._save_contract_files(source_code, contract_dir)

                self.logger.info(f"  ✓ 下载成功: {address.address[:10]}...")
                return True

            except Exception as e:
                self.logger.warning(f"  下载失败 (尝试 {attempt+1}/{API_RETRY_TIMES}): {e}")
                if attempt < API_RETRY_TIMES - 1:
                    time.sleep(API_RETRY_DELAY)

        return False

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


# ============================================================================
# 主控制器
# ============================================================================

class ContractExtractor:
    """主控制器 - 协调各个模块"""

    def __init__(self, test_dir: Path, output_dir: Path, api_keys: Optional[Dict[str, str]] = None):
        self.test_dir = test_dir
        self.output_dir = output_dir

        # 使用传入的api_keys或默认配置
        self.api_keys = api_keys or DEFAULT_API_KEYS

        # 初始化各模块
        self.static_analyzer = StaticAnalyzer()
        self.dynamic_analyzer = DynamicAnalyzer()
        self.source_downloader = SourceDownloader(self.api_keys)

        # 统计信息
        self.summary = ExecutionSummary()

        # 日志
        self.logger = logging.getLogger(__name__ + '.ContractExtractor')

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 错误日志文件
        self.error_log = self.output_dir / 'error.log'
        self.unverified_file = self.output_dir / 'unverified.json'
        self.summary_file = self.output_dir / 'summary.json'

    def extract_all(self, date_filters: Optional[List[str]] = None):
        """
        提取所有脚本的合约

        Args:
            date_filters: 日期过滤器列表,如 ["2025-08","2025-09"]
        """
        self.logger.info("=" * 80)
        self.logger.info("开始提取DeFi攻击合约")
        self.logger.info("=" * 80)

        # 查找所有测试脚本
        scripts = self._find_all_scripts(date_filters)
        self.summary.total_scripts = len(scripts)

        self.logger.info(f"找到 {len(scripts)} 个测试脚本")

        # 处理每个脚本
        unverified_contracts = []

        for i, script in enumerate(scripts, 1):
            self.logger.info(f"\n[{i}/{len(scripts)}] 处理: {script.date_dir}/{script.name}")

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

        # 保存未验证合约列表
        if unverified_contracts:
            with open(self.unverified_file, 'w') as f:
                json.dump(unverified_contracts, f, indent=2)

        # 保存执行摘要
        self._save_summary()

        # 打印统计
        self._print_summary()

    def _find_all_scripts(self, date_filters: Optional[List[str]] = None) -> List[ExploitScript]:
        """查找所有测试脚本"""
        scripts = []

        # 遍历所有日期目录
        for date_dir in sorted(self.test_dir.iterdir()):
            if not date_dir.is_dir():
                continue

            # 匹配 YYYY-MM 格式
            if not re.match(r'\d{4}-\d{2}', date_dir.name):
                continue

            # 应用过滤器
            if date_filters and not any(date_dir.name.startswith(f) for f in date_filters):
                continue

            # 查找该目录下的所有.sol文件
            for sol_file in date_dir.glob('*.sol'):
                script = ExploitScript(
                    file_path=sol_file,
                    name=sol_file.stem,
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
        static_addresses, chain = self.static_analyzer.analyze_script(script)
        script.chain = chain or script.chain

        # 2. 动态分析
        dynamic_addresses = []
        if self.dynamic_analyzer:
            dynamic_addresses = self.dynamic_analyzer.analyze_script(script)

        # 3. 合并地址
        all_addresses = self._merge_addresses(static_addresses, dynamic_addresses, script.chain)

        if not all_addresses:
            self.logger.warning("  未提取到任何地址")
            return False

        self.logger.info(f"  共提取到 {len(all_addresses)} 个唯一地址")
        self.summary.total_addresses += len(all_addresses)

        # 4. 创建输出目录
        script_output_dir = self.output_dir / script.date_dir / script.name
        script_output_dir.mkdir(parents=True, exist_ok=True)

        # 5. 保存地址列表
        self._save_addresses(all_addresses, script_output_dir / 'addresses.json')

        # 6. 下载源码
        if script.chain:
            self._download_sources(all_addresses, script.chain,
                                  script_output_dir, unverified_contracts)
        else:
            self.logger.warning("  未识别链类型,跳过源码下载")

        return True

    def _merge_addresses(self, static: List[ContractAddress],
                        dynamic: List[ContractAddress],
                        chain: Optional[str]) -> List[ContractAddress]:
        """合并静态和动态地址"""
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

        return list(merged.values())

    def _save_addresses(self, addresses: List[ContractAddress], output_file: Path):
        """保存地址列表"""
        data = [asdict(addr) for addr in addresses]
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _download_sources(self, addresses: List[ContractAddress],
                         chain: str, output_dir: Path,
                         unverified_contracts: List[Dict]):
        """下载所有地址的源码"""
        self.logger.info(f"  开始下载源码 (链: {chain})")

        for addr in addresses:
            success = self.source_downloader.download_contract(addr, chain, output_dir)

            if success:
                self.summary.verified_contracts += 1
            else:
                self.summary.unverified_contracts += 1
                unverified_contracts.append({
                    'address': addr.address,
                    'chain': chain,
                    'name': addr.name
                })

    def _log_error(self, message: str):
        """记录错误到日志文件"""
        with open(self.error_log, 'a') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")

    def _save_summary(self):
        """保存执行摘要"""
        self.summary.api_calls = self.source_downloader.api_call_count
        with open(self.summary_file, 'w') as f:
            json.dump(asdict(self.summary), f, indent=2)

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
        self.logger.info(f"API调用次数:     {self.summary.api_calls}")
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

  # 处理所有脚本
  python extract_contracts.py

  # 使用API Key
  python extract_contracts.py --api-key YOUR_API_KEY

  # 同时处理多个目录
  python extract_contracts.py --filter 2025-08 --filter 2025-09

  # 只做静态分析(不运行测试)
  python extract_contracts.py --static-only
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
        '--debug',
        action='store_true',
        help='启用调试日志'
    )

    args = parser.parse_args()

    # 设置日志级别
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

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
        api_keys=api_keys
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
    try:
        extractor.extract_all(date_filters=date_filters)
    except KeyboardInterrupt:
        logger.info("\n\n用户中断,正在保存进度...")
        extractor._save_summary()
        logger.info("进度已保存")


if __name__ == '__main__':
    main()
