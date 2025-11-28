#!/usr/bin/env python3
"""
自动化 Monitor 输出生成脚本（改进版 - Anvil 重放模式）

功能：
1. 从 attack_state.json 读取攻击信息（fork block, 网络等）
2. 启动 Anvil fork 到攻击区块前
3. 部署攻击状态到 Anvil
4. 运行 forge test 在 Anvil 上重放攻击
5. 使用 Go Monitor 分析 Anvil 上的重放交易（获取完整 trace 数据）
6. 生成详细的 monitor 输出文件

工作流对比：
    【旧版】主网原始交易 → Monitor（无法获取 debug trace）→ 简陋输出
    【新版】Anvil 重放交易 → Monitor（完整 debug trace）→ 详细输出

使用示例：
    # 处理单个项目
    python src/test/generate_monitor_output.py \
      --project extracted_contracts/2024-01/BarleyFinance_exp

    # 批量处理整个目录
    python src/test/generate_monitor_output.py \
      --filter 2024-01 \
      --batch

    # 处理所有项目
    python src/test/generate_monitor_output.py --all

作者: Claude Code
版本: 3.0.0 (Anvil Replay Mode)
"""

import os
import sys
import json
import time
import signal
import logging
import argparse
import subprocess
import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import toml

# ============================================================================
# 配置
# ============================================================================

LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# 默认配置（支持环境变量自定义端口，用于并行处理）
ANVIL_PORT = int(os.environ.get('ANVIL_PORT', '8545'))
ANVIL_RPC = f"http://localhost:{ANVIL_PORT}"
# Disable auto-generated dev accounts when forking; some public RPCs reject
# state lookups for the default anvil accounts that never existed on-chain.
ANVIL_DEV_ACCOUNTS = int(os.environ.get("ANVIL_DEV_ACCOUNTS", "0"))
AUTOPATH_DIR = Path("autopath")
MONITOR_BINARY = AUTOPATH_DIR / "monitor"

# 默认链别别名映射
CHAIN_ALIASES = {
    "eth": "mainnet",
    "ethereum": "mainnet",
    "eth-mainnet": "mainnet",
    "ethereum-mainnet": "mainnet",
    "arb": "arbitrum",
    "arbitrum-one": "arbitrum",
    "arbitrum_mainnet": "arbitrum",
    "op": "optimism",
    "optimism-mainnet": "optimism",
    "op-mainnet": "optimism",
    "bnb": "bsc",
    "bnb-chain": "bsc",
    "binance": "bsc",
    "binance-smart-chain": "bsc",
    "polygon-pos": "polygon",
    "matic": "polygon",
    "avax": "avalanche",
    "avalanche-mainnet": "avalanche",
    "fantom-opera": "fantom",
    "fantom-mainnet": "fantom",
    "base-mainnet": "base",
    "linea-mainnet": "linea",
    "blast-mainnet": "blast",
    "gnosis-chain": "gnosis",
    "celo-mainnet": "celo",
}

# 针对部分链提高默认区块 Gas 上限，避免高 gas 交易被拒绝
CHAIN_BLOCK_GAS_LIMITS = {
    "bsc": 200_000_000,
}

# 为不稳定的公开 RPC 提供备用线路（可通过环境变量 ENABLE_RPC_FALLBACKS 启用）
CHAIN_RPC_FALLBACKS = {
    "bsc": [
        "https://bsc-dataseed.binance.org",
        "https://rpc.ankr.com/bsc",
    ],
    "optimism": [
        "https://mainnet.optimism.io",
    ],
}

ENABLE_RPC_FALLBACKS = os.environ.get("ENABLE_RPC_FALLBACKS", "").lower() in ("1", "true", "yes")


def mask_rpc_url(url: Optional[str]) -> str:
    """对 RPC URL 做轻量脱敏，避免日志泄露完整密钥"""
    if not url:
        return "未配置"
    if "://" not in url:
        return url if len(url) <= 16 else f"{url[:6]}...{url[-4:]}"
    scheme, rest = url.split("://", 1)
    if len(rest) <= 16:
        return f"{scheme}://{rest}"
    return f"{scheme}://{rest[:8]}...{rest[-4:]}"


# ============================================================================
# Anvil 管理器
# ============================================================================

class AnvilManager:
    """管理 Anvil 本地链的生命周期"""

    def __init__(
        self,
        rpc_urls: List[str],
        fork_block: int,
        port: int = 8545,
        block_gas_limit: Optional[int] = None,
        dev_accounts: Optional[int] = ANVIL_DEV_ACCOUNTS,
    ):
        self.rpc_urls = [str(url) for url in rpc_urls if url]
        if not self.rpc_urls:
            raise ValueError("至少需要一个 RPC URL 启动 Anvil")
        self.fork_block = fork_block
        self.port = port
        self.block_gas_limit = block_gas_limit
        self.dev_accounts = dev_accounts
        self.process: Optional[subprocess.Popen] = None
        self.log_file = None
        self.active_rpc_url: Optional[str] = None

    def start(self) -> bool:
        """启动 Anvil，支持备用 RPC 和自定义区块 Gas 限制"""
        for attempt, rpc_url in enumerate(self.rpc_urls, start=1):
            masked_rpc = mask_rpc_url(rpc_url)
            total = len(self.rpc_urls)
            logger.info(
                "启动 Anvil (fork block: %s, 端口: %s, RPC: %s) [%s/%s]",
                self.fork_block,
                self.port,
                masked_rpc,
                attempt,
                total,
            )

            self._open_log_file()

            cmd = [
                "anvil",
                "--fork-url",
                rpc_url,
                "--fork-block-number",
                str(self.fork_block),
                "--port",
                str(self.port),
                "--block-base-fee-per-gas",
                "0",
                "--gas-price",
                "0",
            ]
            if self.block_gas_limit:
                cmd.extend(["--block-gas-limit", str(self.block_gas_limit)])
            if self.dev_accounts is not None:
                cmd.extend(["--accounts", str(self.dev_accounts)])

            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=self.log_file,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid,
                )
            except Exception as exc:
                logger.error(f"启动 Anvil 失败: {exc}")
                self._dump_startup_logs()
                self._terminate_process(silent=True)
                continue

            if self._wait_until_ready():
                self.active_rpc_url = rpc_url
                logger.info(
                    "✓ Anvil 启动成功 (PID: %s, 端口: %s)",
                    self.process.pid,
                    self.port,
                )
                return True

            logger.error("Anvil 启动失败 (端口: %s, RPC: %s)", self.port, masked_rpc)
            self._dump_startup_logs()
            self._terminate_process(silent=True)

        return False

    def stop(self):
        """停止 Anvil"""
        self._terminate_process(silent=False)
        self.active_rpc_url = None

    def _open_log_file(self):
        """为当前端口准备日志文件"""
        if self.log_file:
            try:
                self.log_file.close()
            except Exception:
                pass
        self.log_file = open(f"/tmp/anvil_{self.port}.log", "w")

    def _wait_until_ready(self, max_retries: int = 6) -> bool:
        """等待 Anvil 就绪"""
        for retry in range(max_retries):
            time.sleep(1)
            if self._check_anvil():
                return True
            if retry < max_retries - 1:
                logger.debug("等待Anvil启动... (%s/%s)", retry + 1, max_retries)
        return False

    def _check_anvil(self) -> bool:
        """检查 Anvil 是否正在运行"""
        try:
            result = subprocess.run(
                ["cast", "block-number", "--rpc-url", f"http://localhost:{self.port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _dump_startup_logs(self, max_lines: int = 20):
        """回显 Anvil 启动日志，帮助定位失败原因"""
        if not self.log_file:
            return

        try:
            self.log_file.flush()
            os.fsync(self.log_file.fileno())
        except Exception:
            pass

        try:
            with open(self.log_file.name, "r") as log_reader:
                lines = log_reader.readlines()
            snippet = "".join(lines[-max_lines:]).strip()
            if snippet:
                logger.error("Anvil 启动日志片段:\n%s", snippet)
        except Exception as exc:
            logger.debug(f"读取 Anvil 日志失败: {exc}")

    def _terminate_process(self, silent: bool = False):
        """终止 Anvil 进程并清理资源"""
        if self.process:
            try:
                if not silent:
                    logger.info("停止 Anvil...")
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                self.process.wait(timeout=5)
                if not silent:
                    logger.info("✓ Anvil 已停止")
            except Exception as exc:
                if not silent:
                    logger.warning(f"停止 Anvil 时出错: {exc}")
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except Exception:
                    pass
            finally:
                self.process = None

        if self.log_file:
            try:
                self.log_file.close()
            finally:
                self.log_file = None

# ============================================================================
# 状态部署器
# ============================================================================

class StateDeployer:
    """部署攻击状态到 Anvil"""

    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url

    def deploy(self, attack_state_file: Path) -> bool:
        """部署状态"""
        try:
            logger.info(f"部署攻击状态: {attack_state_file.name}...")

            # 检查部署脚本是否存在
            deploy_script = Path("src/test/deploy_to_anvil.py")
            if not deploy_script.exists():
                logger.warning("未找到 deploy_to_anvil.py，跳过状态部署")
                return True  # 不算失败，继续执行

            # 运行部署脚本
            result = subprocess.run(
                [
                    "python", str(deploy_script),
                    "--state-file", str(attack_state_file),
                    "--rpc-url", self.rpc_url
                ],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                logger.info("✓ 状态部署成功")
                if result.stdout:
                    logger.debug(f"部署输出:\n{result.stdout}")
                return True
            else:
                logger.error(f"状态部署失败 (返回码: {result.returncode})")
                if result.stdout:
                    logger.error(f"标准输出:\n{result.stdout}")
                if result.stderr:
                    logger.error(f"错误输出:\n{result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("部署状态超时")
            return False
        except Exception as e:
            logger.error(f"部署状态时出错: {e}")
            import traceback
            traceback.print_exc()
            return False

# ============================================================================
# 攻击执行器
# ============================================================================

class AttackExecutor:
    """执行攻击脚本并获取交易 hash"""

    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url

    def _detect_test_contract(self, exp_file: Path) -> Optional[str]:
        """
        尝试从攻击脚本中识别测试合约名称。

        大多数脚本命名为 ExploitTest/ContractTest 等，需要读取源文件确认。
        优先返回继承了 Test/DSTest 的合约名称，找不到时回退到首个合约。
        """
        try:
            source = exp_file.read_text(encoding="utf-8")
        except Exception as exc:  # pragma: no cover - I/O 辅助日志
            logger.warning(f"读取攻击脚本失败，无法识别测试合约: {exc}")
            return None

        contract_pattern = re.compile(r'contract\s+(\w+)\s*(?:is\s*([^{]+))?\s*\{', re.MULTILINE)
        first_contract: Optional[str] = None

        for match in contract_pattern.finditer(source):
            name = match.group(1)
            inheritance = (match.group(2) or "").replace("\n", " ")
            bases = [base.strip() for base in inheritance.split(",") if base.strip()]

            if first_contract is None:
                first_contract = name

            if any("Test" in base for base in bases):
                return name

        if first_contract != "ExploitTest" and "contract ExploitTest" in source:
            return "ExploitTest"

        return first_contract

    def execute(self, exp_file: Path) -> Optional[str]:
        """
        执行攻击脚本并返回交易 hash

        Args:
            exp_file: 攻击脚本路径 (如 src/test/2024-01/BarleyFinance_exp.sol)

        Returns:
            交易 hash，如果失败则返回 None
        """
        try:
            logger.info(f"执行攻击脚本: {exp_file.name}...")

            # 运行 forge test
            logger.info("开始编译和执行测试...")
            match_contract = self._detect_test_contract(exp_file)
            if match_contract:
                logger.debug(f"识别到测试合约: {match_contract}")
            else:
                logger.warning("未能识别测试合约名称，默认使用 ExploitTest")
                match_contract = "ExploitTest"

            command = [
                "forge", "test",
                "--match-path", str(exp_file),
                "--match-contract", match_contract,
                "--skip", "src/test/2025-05/Corkprotocol_exp.sol",  # 已知 Stack too deep
                "--skip", "src/test/2024-11/proxy_b7e1_exp.sol",    # 已知 Stack too deep
                "--skip", "src/test/2024-01/XSIJ_exp.sol",          # 导入 Firewall IRouter
                "--skip", "src/test/2024-01/XSIJ_exp.sol.backup",   # 导入 Firewall IRouter
                "--rpc-url", self.rpc_url,
                "-vvv"  # 详细输出以便获取 tx hash
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=600  # 增加到 10 分钟
            )

            if result.returncode != 0:
                logger.error(f"攻击脚本执行失败 (返回码: {result.returncode})")
                if result.stdout:
                    logger.error(f"标准输出:\n{result.stdout[-500:]}")  # 只显示最后500字符
                if result.stderr:
                    logger.error(f"错误输出:\n{result.stderr[-500:]}")  # 只显示最后500字符
                return None

            # 测试成功执行
            logger.info("✓ 测试执行成功")

            # 先尝试从输出中提取交易 hash
            tx_hash = self._extract_tx_hash(result.stdout + result.stderr)

            if not tx_hash:
                # 如果没有找到，立即从 Anvil 查询最新交易（在停止 Anvil 之前）
                logger.warning("未从输出中找到交易 hash，尝试查询最新交易...")
                tx_hash = self._get_latest_tx()

            if tx_hash:
                logger.info(f"✓ 攻击执行成功，交易: {tx_hash}")
                return tx_hash
            else:
                logger.error("无法获取交易 hash")
                return None

        except subprocess.TimeoutExpired:
            logger.error("攻击脚本执行超时")
            return None
        except Exception as e:
            logger.error(f"执行攻击时出错: {e}")
            return None

    def _extract_tx_hash(self, output: str) -> Optional[str]:
        """从输出中提取交易 hash"""
        # 尝试多种模式匹配
        patterns = [
            r'Transaction:\s+(0x[a-fA-F0-9]{64})',
            r'hash:\s+(0x[a-fA-F0-9]{64})',
            r'txHash:\s+(0x[a-fA-F0-9]{64})',
            r'\[PASS\].*\(gas:\s+\d+\).*?(0x[a-fA-F0-9]{64})',
        ]

        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1)

        return None

    def _get_latest_tx(self) -> Optional[str]:
        """从最新区块获取最后一笔交易"""
        try:
            # 方法1: 获取最新区块号
            result = subprocess.run(
                ["cast", "block-number", "--rpc-url", self.rpc_url],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                logger.debug("获取区块号失败")
                return None

            block_number = int(result.stdout.strip())
            logger.debug(f"最新区块号: {block_number}")

            # 方法2: 遍历最近几个区块，查找交易
            for i in range(5):  # 检查最近5个区块
                current_block = block_number - i
                result = subprocess.run(
                    [
                        "cast", "block", str(current_block),
                        "--rpc-url", self.rpc_url,
                        "--json"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    try:
                        block = json.loads(result.stdout)
                        transactions = block.get('transactions', [])

                        if transactions:
                            # 获取最后一笔交易
                            if isinstance(transactions[-1], str):
                                tx_hash = transactions[-1]
                            elif isinstance(transactions[-1], dict):
                                tx_hash = transactions[-1].get('hash')
                            else:
                                continue

                            if tx_hash and tx_hash.startswith('0x') and len(tx_hash) == 66:
                                logger.debug(f"找到交易: {tx_hash} (区块 {current_block})")
                                return tx_hash
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            logger.debug(f"获取最新交易失败: {e}")

        return None

# ============================================================================
# 状态收集器
# ============================================================================

class StateCollector:
    """收集 Anvil/链上的合约状态"""

    def __init__(self, rpc_url: str):
        """
        初始化状态收集器

        Args:
            rpc_url: RPC 端点 URL
        """
        try:
            from web3 import Web3
            self.Web3 = Web3
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
            self.logger = logging.getLogger(__name__ + '.StateCollector')

            # 测试连接
            if not self.w3.is_connected():
                self.logger.warning(f"无法连接到 RPC: {rpc_url}")
            else:
                self.logger.debug(f"✓ 已连接到 RPC: {rpc_url}")

        except ImportError:
            self.logger.error("需要安装 web3 库: pip install web3")
            raise
        except Exception as e:
            self.logger.error(f"初始化 StateCollector 失败: {e}")
            raise

    def collect_storage_for_known_slots(
        self,
        address: str,
        known_slots: List[str]
    ) -> Dict[str, str]:
        """
        收集已知槽位的存储值

        Args:
            address: 合约地址
            known_slots: 已知槽位列表 (来自 attack_state.json)

        Returns:
            槽位 -> 值的映射 {"0x2": "0x123...", ...}
        """
        storage = {}

        for slot in known_slots:
            try:
                # 转换槽号为整数
                if isinstance(slot, str):
                    if slot.startswith('0x'):
                        slot_int = int(slot, 16)
                    else:
                        slot_int = int(slot)
                else:
                    slot_int = int(slot)

                # 查询存储值
                value = self.w3.eth.get_storage_at(address, slot_int)

                # 转换为十六进制字符串
                if isinstance(value, bytes):
                    storage[slot] = '0x' + value.hex()
                elif isinstance(value, self.Web3.HexBytes):
                    storage[slot] = value.hex()
                else:
                    storage[slot] = str(value)

            except Exception as e:
                self.logger.debug(f"查询 slot {slot} 失败 ({address[:10]}...): {e}")
                storage[slot] = "0x0"

        return storage

    def collect(
        self,
        addresses_with_slots: Dict[str, List[str]],
        output_file: Path,
        label: str = "state",
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        收集指定地址的完整状态

        Args:
            addresses_with_slots: {地址: [槽位列表]} 映射
            output_file: 输出文件路径
            label: 状态标签 (before/after)
            metadata: 额外的元数据信息

        Returns:
            是否成功
        """
        try:
            current_block = self.w3.eth.block_number

            state_data = {
                "metadata": {
                    "label": label,
                    "collected_at": datetime.now().isoformat(),
                    "block_number": current_block,
                    "total_addresses": len(addresses_with_slots),
                    **(metadata or {})
                },
                "addresses": {}
            }

            for addr, known_slots in addresses_with_slots.items():
                self.logger.debug(f"收集 {addr[:10]}... 的状态")

                # 1. 查询基础信息
                try:
                    balance = self.w3.eth.get_balance(addr)
                    code = self.w3.eth.get_code(addr)
                    nonce = self.w3.eth.get_transaction_count(addr)

                    # 转换 code 为十六进制字符串
                    if isinstance(code, bytes):
                        code_hex = '0x' + code.hex()
                    elif isinstance(code, self.Web3.HexBytes):
                        code_hex = code.hex()
                    else:
                        code_hex = str(code)

                    # 2. 查询存储槽
                    storage = self.collect_storage_for_known_slots(addr, known_slots)

                    state_data["addresses"][addr] = {
                        "balance_wei": str(balance),
                        "nonce": nonce,
                        "code": code_hex,
                        "code_size": len(code_hex) // 2 if code_hex.startswith('0x') else len(code_hex),
                        "is_contract": len(code_hex) > 2,
                        "storage": storage
                    }

                except Exception as e:
                    self.logger.warning(f"收集 {addr[:10]}... 失败: {e}")
                    state_data["addresses"][addr] = {
                        "error": str(e)
                    }

            # 保存到文件
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, indent=2, ensure_ascii=False)

            self.logger.info(f"✓ 状态已保存: {output_file} ({len(addresses_with_slots)} 个地址)")
            return True

        except Exception as e:
            self.logger.error(f"收集状态失败: {e}")
            import traceback
            traceback.print_exc()
            return False

# ============================================================================
# Monitor 运行器
# ============================================================================

class MonitorRunner:
    """运行 Go Monitor 分析交易"""

    def __init__(self, monitor_binary: Path, rpc_url: str):
        self.monitor_binary = monitor_binary
        self.rpc_url = rpc_url

    def ensure_compiled(self) -> bool:
        """确保 Monitor 已编译"""
        if self.monitor_binary.exists():
            logger.info(f"✓ Monitor 二进制已存在")
            return True

        logger.info("Monitor 未编译，开始编译...")
        return self._compile()

    def _compile(self) -> bool:
        """编译 Go Monitor"""
        try:
            autopath_dir = self.monitor_binary.parent

            # 检查 Go 源码是否存在
            if not (autopath_dir / "cmd" / "monitor").exists():
                logger.error(f"未找到 Monitor 源码目录: {autopath_dir}/cmd/monitor")
                return False

            logger.info("下载 Go 依赖...")
            result = subprocess.run(
                ["go", "mod", "download"],
                cwd=autopath_dir,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode != 0:
                logger.error(f"下载依赖失败:\n{result.stderr}")
                return False

            logger.info("编译 Monitor...")
            result = subprocess.run(
                ["go", "build", "-o", "monitor", "./cmd/monitor"],
                cwd=autopath_dir,
                capture_output=True,
                text=True,
                timeout=180
            )

            if result.returncode == 0:
                logger.info(f"✓ Monitor 编译成功")
                return True
            else:
                logger.error(f"编译失败:\n{result.stderr}")
                return False

        except Exception as e:
            logger.error(f"编译 Monitor 时出错: {e}")
            return False

    def analyze(self, tx_hash: str, output_file: Path, project_name: str = "") -> bool:
        """
        运行 Monitor 分析交易

        Args:
            tx_hash: 交易 hash
            output_file: 输出文件路径
            project_name: 项目名称（可选）

        Returns:
            是否成功
        """
        try:
            logger.info(f"运行 Monitor 分析交易...")
            logger.info(f"  交易: {tx_hash}")
            logger.info(f"  输出: {output_file}")

            # 构建命令
            cmd = [
                str(self.monitor_binary),
                "-rpc", self.rpc_url,
                "-tx", tx_hash,
                "-output", str(output_file),
                "-v"
            ]

            if project_name:
                cmd.extend(["-event", project_name])

            # 运行 Monitor
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                logger.info("✓ Monitor 分析完成")
                logger.info(f"  结果已保存到: {output_file}")
                return True
            else:
                logger.error(f"Monitor 分析失败:\n{result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Monitor 分析超时")
            return False
        except Exception as e:
            logger.error(f"运行 Monitor 时出错: {e}")
            return False

# ============================================================================
# 主控制器
# ============================================================================

class MonitorOutputGenerator:
    """Monitor 输出生成的主控制器（改进版 - Anvil 重放模式）"""

    def __init__(self, rpc_url: str = "https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"):
        self.default_rpc_url = rpc_url
        self.rpc_endpoints = self._load_foundry_rpc_endpoints()
        # Monitor 连接到 Anvil 分析重放交易
        self.monitor_runner = MonitorRunner(MONITOR_BINARY, ANVIL_RPC)

    def generate_for_project(self, project_dir: Path) -> bool:
        """
        为单个项目生成 Monitor 输出（改进版 - Anvil 重放模式）

        Args:
            project_dir: 项目目录 (如 extracted_contracts/2024-01/BarleyFinance_exp)

        Returns:
            是否成功
        """
        logger.info("="*80)
        logger.info(f"处理项目: {project_dir.name}")
        logger.info("="*80)

        anvil_manager = None

        try:
            # 1. 检查必需文件
            attack_state_file = project_dir / "attack_state.json"
            if not attack_state_file.exists():
                logger.error(f"未找到 attack_state.json: {attack_state_file}")
                return False

            # 2. 加载攻击状态元数据
            logger.info(f"\n[1/6] 读取 attack_state.json...")
            with open(attack_state_file) as f:
                attack_state = json.load(f)
                metadata = attack_state.get('metadata', {})

            # 提取关键信息
            fork_block = metadata.get('block_number')
            chain = metadata.get('chain', 'mainnet')
            normalized_chain = self._normalize_chain_name(chain)
            original_tx_hash = metadata.get('attack_tx_hash')

            if not fork_block:
                logger.error("attack_state.json 中未找到 block_number")
                return False

            rpc_url, rpc_source = self._resolve_rpc_url(chain)
            logger.info(f"✓ 链: {chain}")
            logger.info(f"✓ Fork 区块: {fork_block}")
            logger.info(f"✓ 原始交易: {original_tx_hash}")
            logger.info(f"✓ RPC 来源: {rpc_source} ({mask_rpc_url(rpc_url)})")

            rpc_candidates = self._build_rpc_candidates(normalized_chain, rpc_url)
            if not rpc_candidates:
                logger.error("未找到可用 RPC，无法启动 Anvil")
                return False

            fork_start_block = max(fork_block - 1, 0)
            block_gas_limit = CHAIN_BLOCK_GAS_LIMITS.get(normalized_chain)

            # 3. 启动 Anvil fork 到攻击区块前一个区块
            logger.info(f"\n[2/6] 启动 Anvil...")
            if block_gas_limit:
                logger.info(f"  自定义区块 Gas 限制: {block_gas_limit}")

            anvil_manager = AnvilManager(
                rpc_candidates,
                fork_start_block,
                ANVIL_PORT,
                block_gas_limit=block_gas_limit,
                dev_accounts=ANVIL_DEV_ACCOUNTS,
            )
            if not anvil_manager.start():
                logger.error("启动 Anvil 失败")
                return False
            if (
                anvil_manager.active_rpc_url
                and rpc_url
                and anvil_manager.active_rpc_url != rpc_url
            ):
                logger.info(
                    "  已切换到备用 RPC: %s",
                    mask_rpc_url(anvil_manager.active_rpc_url),
                )

            # 4. 部署攻击状态到 Anvil
            logger.info(f"\n[3/6] 部署攻击状态到 Anvil...")
            state_deployer = StateDeployer(ANVIL_RPC)
            if not state_deployer.deploy(attack_state_file):
                logger.warning("状态部署失败或跳过，继续执行...")

            # 5. 查找并运行攻击脚本
            logger.info(f"\n[4/6] 在 Anvil 上重放攻击...")
            exp_file = self._find_exp_file(project_dir.name)
            if not exp_file:
                logger.error(f"未找到攻击脚本: {project_dir.name}.sol")
                return False

            logger.info(f"  攻击脚本: {exp_file}")
            attack_executor = AttackExecutor(ANVIL_RPC)
            anvil_tx_hash = attack_executor.execute(exp_file)

            if not anvil_tx_hash:
                logger.error("重放攻击失败，无法获取交易 hash")
                return False

            logger.info(f"✓ 重放成功，Anvil 交易: {anvil_tx_hash}")

            # 5.5. 收集攻击后状态
            logger.info(f"\n[4.5/6] 收集攻击后状态...")
            after_state_file = project_dir / "attack_state_after.json"

            try:
                # 创建状态收集器
                state_collector = StateCollector(ANVIL_RPC)

                # 读取原始 attack_state.json 获取地址和槽位列表
                addresses_with_slots = {}
                for addr, addr_data in before_state['addresses'].items():
                    # 获取该地址的已知槽位列表
                    known_slots = list(addr_data.get('storage', {}).keys())
                    if known_slots:  # 只收集有存储槽的地址
                        addresses_with_slots[addr] = known_slots

                if addresses_with_slots:
                    # 收集攻击后状态
                    success = state_collector.collect(
                        addresses_with_slots=addresses_with_slots,
                        output_file=after_state_file,
                        label="after_attack",
                        metadata={
                            "attack_tx_hash": anvil_tx_hash,
                            "original_attack_tx": original_tx_hash
                        }
                    )

                    if success:
                        logger.info(f"✓ 攻击后状态已保存: {after_state_file.name}")
                    else:
                        logger.warning("收集攻击后状态失败，继续执行...")
                else:
                    logger.warning("未找到需要收集的存储槽，跳过状态收集")

            except Exception as e:
                logger.warning(f"收集攻击后状态时出错: {e}")
                logger.warning("继续执行剩余流程...")

            # 6. 确保 Monitor 已编译
            logger.info(f"\n[5/6] 检查 Monitor 二进制...")
            if not self.monitor_runner.ensure_compiled():
                return False

            # 7. 使用 Monitor 分析 Anvil 上的交易（现在可以获取完整 trace）
            logger.info(f"\n[6/6] 运行 Monitor 分析 Anvil 交易...")
            output_file = AUTOPATH_DIR / f"{project_dir.name}_analysis.json"

            # 创建连接到 Anvil 的 MonitorRunner
            anvil_monitor = MonitorRunner(MONITOR_BINARY, ANVIL_RPC)
            if not anvil_monitor.analyze(anvil_tx_hash, output_file, project_dir.name):
                return False

            logger.info("="*80)
            logger.info(f"✓ 项目 {project_dir.name} 处理成功")
            logger.info(f"  原始交易: {original_tx_hash}")
            logger.info(f"  Anvil 交易: {anvil_tx_hash}")
            logger.info(f"  输出文件: {output_file}")
            logger.info("="*80)

            return True

        except Exception as e:
            logger.error(f"处理项目时出错: {e}")
            import traceback
            traceback.print_exc()
            return False

        finally:
            # 8. 清理：停止 Anvil
            if anvil_manager:
                logger.info("\n[清理] 停止 Anvil...")
                anvil_manager.stop()

    def generate_batch(self, filter_pattern: str = None) -> Dict[str, bool]:
        """
        批量生成多个项目的 Monitor 输出

        Args:
            filter_pattern: 过滤模式 (如 "2024-01")

        Returns:
            项目名 -> 是否成功的字典
        """
        results = {}

        # 查找所有项目
        projects = self._find_projects(filter_pattern)

        logger.info(f"找到 {len(projects)} 个项目")

        for i, project_dir in enumerate(projects, 1):
            logger.info(f"\n[{i}/{len(projects)}] 处理项目: {project_dir.name}")

            success = self.generate_for_project(project_dir)
            results[project_dir.name] = success

            # 等待一下，确保资源释放
            time.sleep(2)

        return results

    def _find_projects(self, filter_pattern: str = None) -> List[Path]:
        """查找所有项目目录"""
        base_dir = Path("extracted_contracts")

        if not base_dir.exists():
            return []

        projects = []

        # 遍历所有子目录
        for year_month_dir in base_dir.iterdir():
            if not year_month_dir.is_dir():
                continue

            # 应用过滤
            if filter_pattern and filter_pattern not in str(year_month_dir):
                continue

            for project_dir in year_month_dir.iterdir():
                if not project_dir.is_dir():
                    continue

                # 检查是否有 attack_state.json
                if (project_dir / "attack_state.json").exists():
                    projects.append(project_dir)

        return sorted(projects)

    def _find_exp_file(self, project_name: str) -> Optional[Path]:
        """查找攻击脚本文件"""
        # 尝试多个可能的位置
        possible_paths = [
            Path(f"src/test/{project_name}.sol"),
            Path("src/test") / "2024-01" / f"{project_name}.sol",
            Path("src/test") / "2024-02" / f"{project_name}.sol",
        ]

        # 也尝试搜索
        test_dir = Path("src/test")
        if test_dir.exists():
            for exp_file in test_dir.rglob(f"{project_name}.sol"):
                return exp_file

        for path in possible_paths:
            if path.exists():
                return path

        return None

    def _load_foundry_rpc_endpoints(self) -> Dict[str, str]:
        """从 foundry.toml 读取 rpc_endpoints 配置"""
        cfg_path = Path("foundry.toml")
        if not cfg_path.exists():
            logger.debug("未找到 foundry.toml，无法加载链上 RPC 映射")
            return {}

        try:
            data = toml.load(cfg_path)
            endpoints = data.get("rpc_endpoints", {})
            normalized = {}
            for key, value in endpoints.items():
                if isinstance(key, str) and isinstance(value, str) and value:
                    normalized[key.lower()] = value
            if not normalized:
                logger.debug("foundry.toml 中未配置 rpc_endpoints")
            return normalized
        except Exception as exc:
            logger.warning(f"解析 foundry.toml 失败: {exc}")
            return {}

    def _normalize_chain_name(self, chain: Optional[str]) -> str:
        """归一化链名称"""
        if not chain:
            return "mainnet"
        name = chain.strip().lower()
        return CHAIN_ALIASES.get(name, name)

    def _resolve_rpc_url(self, chain: Optional[str]) -> Tuple[str, str]:
        """
        根据链信息决定使用的 RPC

        Returns:
            (rpc_url, source_description)
        """
        normalized = self._normalize_chain_name(chain)

        # 优先读取环境变量（允许用户覆盖）
        env_key = f"RPC_{normalized.upper()}"
        env_value = os.environ.get(env_key)
        if env_value:
            return env_value, f"env:{env_key}"

        # 再尝试 foundry.toml 中的 rpc_endpoints
        if normalized in self.rpc_endpoints:
            return self.rpc_endpoints[normalized], f"foundry:{normalized}"

        # mainnet 默认使用 CLI 参数
        if normalized in ("mainnet", "ethereum", "eth"):
            return self.default_rpc_url, "default:mainnet"

        # 未匹配时回退到默认值
        logger.warning(f"未找到链 {chain} 对应的 RPC 配置，回退到默认 RPC")
        return self.default_rpc_url, f"default:{normalized}"

    def _build_rpc_candidates(self, normalized_chain: str, primary_url: Optional[str]) -> List[str]:
        """构造首选 + 备用 RPC 列表"""
        candidates: List[str] = []

        if primary_url:
            candidates.append(primary_url)

        if ENABLE_RPC_FALLBACKS:
            for fallback in CHAIN_RPC_FALLBACKS.get(normalized_chain, []):
                if fallback and fallback not in candidates:
                    candidates.append(fallback)

        return candidates

# ============================================================================
# 命令行接口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='自动化生成 Monitor 输出文件（改进版 - Anvil 重放模式）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
工作流程:
  1. 读取 attack_state.json（包含 fork block 等信息）
  2. 启动 Anvil fork 到攻击区块
  3. 部署攻击状态到 Anvil
  4. 运行 forge test 在 Anvil 上重放攻击
  5. 使用 Monitor 分析 Anvil 交易（获取完整 debug trace）
  6. 生成详细的分析报告

示例:
  # 处理单个项目（推荐）
  python src/test/generate_monitor_output.py \\
    --project extracted_contracts/2024-01/BarleyFinance_exp

  # 批量处理 2024-01 目录下的所有项目
  python src/test/generate_monitor_output.py \\
    --filter 2024-01 \\
    --batch

  # 处理所有项目
  python src/test/generate_monitor_output.py --all

  # 指定自定义 RPC（用于 fork 主网）
  python src/test/generate_monitor_output.py \\
    --project extracted_contracts/2024-01/BarleyFinance_exp \\
    --rpc-url https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY

注意事项:
  - 需要确保 Anvil 可用（foundry 工具链）
  - 需要确保 autopath/monitor 已编译
  - 每个项目会独立启动/停止 Anvil
  - Anvil 会临时占用 8545 端口
        """
    )

    parser.add_argument(
        '--project',
        type=Path,
        help='单个项目目录路径'
    )

    parser.add_argument(
        '--filter',
        help='批量处理时的过滤模式 (如 "2024-01")'
    )

    parser.add_argument(
        '--batch',
        action='store_true',
        help='批量处理模式'
    )

    parser.add_argument(
        '--all',
        action='store_true',
        help='处理所有项目'
    )

    parser.add_argument(
        '--rpc-url',
        default='https://eth-mainnet.g.alchemy.com/v2/oKxs-03sij-U_N0iOlrSsZFr29-IqbuF',
        help='主网 RPC URL（用于 Anvil fork）'
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

    # 创建生成器
    generator = MonitorOutputGenerator(args.rpc_url)

    # 根据参数执行
    if args.project:
        # 单个项目模式
        success = generator.generate_for_project(args.project)
        return 0 if success else 1

    elif args.batch or args.all:
        # 批量模式
        filter_pattern = args.filter if not args.all else None
        results = generator.generate_batch(filter_pattern)

        # 打印汇总
        logger.info("\n" + "="*80)
        logger.info("批量处理结果汇总")
        logger.info("="*80)

        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)

        for project_name, success in results.items():
            status = "✓" if success else "✗"
            logger.info(f"{status} {project_name}")

        logger.info("="*80)
        logger.info(f"成功: {success_count}/{total_count}")
        logger.info("="*80)

        return 0 if success_count == total_count else 1

    else:
        parser.print_help()
        return 1

if __name__ == '__main__':
    sys.exit(main())
