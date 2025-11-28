#!/usr/bin/env python3
"""
链上数据获取模块 - OnChain Data Fetcher

提供高并发、智能缓存的链上合约信息获取能力,支持:
- 多API密钥轮询和负载均衡
- 异步批量获取(15请求/秒)
- 本地文件缓存(24小时TTL)
- 自动重试和错误处理

作者: FirewallOnchain Team
版本: 1.0.0
日期: 2025-01-21
"""

import asyncio
import aiohttp
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import logging
from web3 import Web3
from web3.exceptions import ContractLogicError

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# API密钥池 - 实现轮询和限流
# =============================================================================

class APIKeyPool:
    """
    API密钥池 - 管理多个API密钥的轮询使用和限流

    功能:
    - 轮询使用多个密钥,实现负载均衡
    - 滑动窗口限流(每个密钥3次/秒)
    - 自动等待当所有密钥都达到限流时
    """

    def __init__(self, keys: List[str], rate_limit: int = 3):
        """
        初始化API密钥池

        Args:
            keys: API密钥列表
            rate_limit: 每个密钥每秒最大请求数
        """
        if not keys:
            raise ValueError("API密钥列表不能为空")

        self.keys = keys
        self.rate_limit = rate_limit
        # 记录每个密钥的请求时间戳(滑动窗口)
        self.request_counts = {key: [] for key in keys}
        # 统计每个密钥的使用次数
        self.key_usage = {key: 0 for key in keys}

        logger.info(f"API密钥池已初始化: {len(keys)}个密钥, 限流{rate_limit}次/秒")

    def get_available_key(self) -> str:
        """
        获取当前可用的API密钥

        策略:
        1. 遍历所有密钥,找到第一个未达到限流的密钥
        2. 如果所有密钥都达到限流,等待最早的请求过期
        3. 使用滑动窗口算法,清理1秒前的请求记录

        Returns:
            可用的API密钥
        """
        now = time.time()

        # 遍历所有密钥
        for key in self.keys:
            # 清理1秒前的请求记录(滑动窗口)
            self.request_counts[key] = [
                timestamp for timestamp in self.request_counts[key]
                if now - timestamp < 1.0
            ]

            # 如果此密钥在当前秒内请求次数<限流值,返回它
            if len(self.request_counts[key]) < self.rate_limit:
                self.request_counts[key].append(now)
                self.key_usage[key] += 1
                return key

        # 所有密钥都达到限流,计算需要等待的时间
        min_wait_time = min(
            1.0 - (now - min(counts))
            for counts in self.request_counts.values()
            if counts
        )

        logger.debug(f"所有密钥已达限流,等待{min_wait_time:.3f}秒")
        time.sleep(min_wait_time + 0.01)  # +0.01避免边界情况

        # 递归调用,重新获取
        return self.get_available_key()

    def get_stats(self) -> Dict:
        """获取密钥池使用统计"""
        return {
            "total_keys": len(self.keys),
            "rate_limit": self.rate_limit,
            "key_usage": self.key_usage,
            "total_requests": sum(self.key_usage.values())
        }


# =============================================================================
# 文件缓存 - 本地持久化缓存
# =============================================================================

class FileCache:
    """
    文件缓存系统 - 本地持久化链上数据

    功能:
    - 按地址存储,每个地址一个JSON文件
    - 支持TTL过期机制(默认24小时)
    - 自动创建缓存目录
    """

    def __init__(self, cache_dir: Path):
        """
        初始化文件缓存

        Args:
            cache_dir: 缓存目录路径
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"文件缓存已初始化: {self.cache_dir}")

    def get(self, address: str) -> Optional[dict]:
        """
        获取缓存数据

        Args:
            address: 合约地址

        Returns:
            缓存的数据,如果不存在或已过期则返回None
        """
        cache_file = self.cache_dir / f"{address.lower()}.json"

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r') as f:
                cached = json.load(f)

            # 检查是否过期
            if self.is_expired(cached):
                logger.debug(f"缓存已过期: {address}")
                cache_file.unlink()  # 删除过期缓存
                return None

            logger.debug(f"缓存命中: {address}")
            return cached

        except Exception as e:
            logger.warning(f"读取缓存失败 {address}: {e}")
            return None

    def set(self, address: str, data: dict, ttl: int = 86400):
        """
        设置缓存数据

        Args:
            address: 合约地址
            data: 要缓存的数据
            ttl: 生存时间(秒),默认24小时
        """
        cache_file = self.cache_dir / f"{address.lower()}.json"

        cache_data = {
            "data": data,
            "timestamp": time.time(),
            "ttl": ttl
        }

        try:
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)

            logger.debug(f"缓存已保存: {address}")

        except Exception as e:
            logger.warning(f"保存缓存失败 {address}: {e}")

    def is_expired(self, cached: dict) -> bool:
        """
        检查缓存是否过期

        Args:
            cached: 缓存数据(包含timestamp和ttl)

        Returns:
            True if 过期, False otherwise
        """
        if not cached or 'timestamp' not in cached or 'ttl' not in cached:
            return True

        age = time.time() - cached['timestamp']
        return age > cached['ttl']

    def clear(self):
        """清空所有缓存"""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
        logger.info("缓存已清空")

    def get_stats(self) -> Dict:
        """获取缓存统计信息"""
        cache_files = list(self.cache_dir.glob("*.json"))
        total = len(cache_files)

        expired = 0
        for cache_file in cache_files:
            try:
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                if self.is_expired(cached):
                    expired += 1
            except:
                pass

        return {
            "total_cached": total,
            "expired": expired,
            "valid": total - expired
        }


# =============================================================================
# OnChain数据获取器 - 主控制器
# =============================================================================

class OnChainDataFetcher:
    """
    链上数据获取器 - 异步批量获取合约信息

    功能:
    - 从区块链浏览器API获取合约名称、ABI
    - 通过Web3 RPC调用获取ERC20信息
    - 智能缓存和重试
    - 语义类型推断
    """

    def __init__(
        self,
        api_keys: Dict[str, List[str]],
        explorer_urls: Dict[str, str],
        rate_limits: Dict[str, int],
        cache_dir: Path,
        rpc_urls: Optional[Dict[str, str]] = None
    ):
        """
        初始化数据获取器

        Args:
            api_keys: {"etherscan": [...], "bscscan": [...]}
            explorer_urls: {"mainnet": "https://api.etherscan.io/api", ...}
            rate_limits: {"etherscan": 3, "bscscan": 5}
            cache_dir: 缓存目录
            rpc_urls: {"mainnet": "https://eth.llamarpc.com", ...}
        """
        # 为每个链创建API密钥池
        self.key_pools = {}
        for chain, keys in api_keys.items():
            if keys:  # 只为有密钥的链创建池
                self.key_pools[chain] = APIKeyPool(keys, rate_limits.get(chain, 5))

        self.explorer_urls = explorer_urls
        self.cache = FileCache(cache_dir)

        # 初始化Web3实例池(用于RPC调用)
        self.rpc_urls = rpc_urls or self._get_default_rpc_urls()
        self.web3_instances = {}
        for chain, rpc_url in self.rpc_urls.items():
            try:
                self.web3_instances[chain] = Web3(Web3.HTTPProvider(rpc_url))
                logger.info(f"Web3连接成功: {chain} -> {rpc_url}")
            except Exception as e:
                logger.warning(f"Web3连接失败 {chain}: {e}")

        logger.info(f"OnChainDataFetcher已初始化: {len(self.key_pools)}个链, {len(self.web3_instances)}个RPC节点")

    def _get_default_rpc_urls(self) -> Dict[str, str]:
        """获取默认的公共RPC端点"""
        return {
            "mainnet": "https://eth.llamarpc.com",
            "bsc": "https://bsc-dataseed.binance.org",
            "arbitrum": "https://arb1.arbitrum.io/rpc",
            "optimism": "https://mainnet.optimism.io",
            "polygon": "https://polygon-rpc.com",
            "avalanche": "https://api.avax.network/ext/bc/C/rpc",
            "fantom": "https://rpc.ftm.tools"
        }

    @classmethod
    def from_config(cls, config_path: str):
        """
        从配置文件创建实例

        Args:
            config_path: config/api_keys.json路径

        Returns:
            OnChainDataFetcher实例
        """
        config_file = Path(config_path)

        if not config_file.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_file, 'r') as f:
            config = json.load(f)

        # 缓存目录
        cache_dir = config_file.parent.parent / "extracted_contracts" / ".cache" / "onchain_data"

        return cls(
            api_keys=config,
            explorer_urls=config.get("explorer_urls", {}),
            rate_limits=config.get("rate_limits", {}),
            cache_dir=cache_dir,
            rpc_urls=config.get("rpc_urls")  # 如果配置文件有RPC URL则使用,否则用默认值
        )

    async def batch_fetch_contracts(
        self,
        addresses: List[str],
        chain: str = "mainnet"
    ) -> Dict[str, dict]:
        """
        批量获取合约信息(异步并发)

        Args:
            addresses: 合约地址列表
            chain: 链名称(mainnet, bsc, arbitrum等)

        Returns:
            {address: contract_info}
        """
        logger.info(f"开始批量获取 {len(addresses)} 个合约信息 (chain={chain})")

        start_time = time.time()

        # 创建异步任务
        tasks = [
            self._fetch_single_contract(addr, chain)
            for addr in addresses
        ]

        # 并发执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 整理结果 - 使用小写地址作为键以保证匹配
        result_dict = {}
        success_count = 0
        for addr, result in zip(addresses, results):
            # 重要: 使用小写地址作为键,与extract_contracts.py中的匹配逻辑一致
            addr_key = addr.lower()
            if isinstance(result, Exception):
                logger.error(f"获取失败 {addr}: {result}")
                result_dict[addr_key] = {"error": str(result)}
            else:
                result_dict[addr_key] = result
                if result:
                    success_count += 1

        elapsed = time.time() - start_time
        logger.info(f"批量获取完成: {success_count}/{len(addresses)} 成功, 耗时{elapsed:.2f}秒")

        return result_dict

    async def _fetch_single_contract(
        self,
        address: str,
        chain: str
    ) -> dict:
        """
        获取单个合约的信息

        流程:
        1. 检查缓存
        2. 并发获取多个数据源
        3. 融合结果
        4. 保存缓存

        Args:
            address: 合约地址
            chain: 链名称

        Returns:
            合约信息字典
        """
        # 1. 检查缓存
        cached = self.cache.get(address)
        if cached:
            return cached['data']

        # 2. 获取数据
        try:
            async with aiohttp.ClientSession() as session:
                # 并发获取多个API
                contract_name, abi, is_erc20, token_info = await asyncio.gather(
                    self._fetch_contract_name(session, address, chain),
                    self._fetch_contract_abi(session, address, chain),
                    self._check_if_erc20(session, address, chain),
                    self._fetch_token_info(session, address, chain),
                    return_exceptions=True
                )

            # 3. 融合结果
            result = {
                "contract_name": contract_name if not isinstance(contract_name, Exception) else None,
                "is_verified": abi is not None and not isinstance(abi, Exception),
                "is_erc20": is_erc20 if not isinstance(is_erc20, Exception) else False,
            }

            # 添加token信息
            if token_info and not isinstance(token_info, Exception):
                result.update(token_info)

            # 推断语义类型
            result["semantic_type"] = self._infer_semantic_type(
                result.get("contract_name"),
                token_info.get("symbol") if token_info and not isinstance(token_info, Exception) else None
            )

            # 4. 缓存
            self.cache.set(address, result, ttl=86400)

            return result

        except Exception as e:
            logger.error(f"获取合约信息失败 {address}: {e}")
            return {"error": str(e)}

    async def _fetch_contract_name(
        self,
        session: aiohttp.ClientSession,
        address: str,
        chain: str,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        从区块链浏览器获取合约名称

        使用 getsourcecode API
        """
        api_key = self._get_api_key(chain)
        if not api_key:
            return None

        url = self.explorer_urls.get(chain)
        if not url:
            logger.warning(f"未配置chain={chain}的explorer URL")
            return None

        params = {
            "module": "contract",
            "action": "getsourcecode",
            "address": address,
            "apikey": api_key
        }

        for attempt in range(max_retries):
            try:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()

                        if data.get("status") == "1" and data.get("result"):
                            result = data["result"][0] if isinstance(data["result"], list) else data["result"]
                            contract_name = result.get("ContractName")

                            if contract_name:
                                logger.debug(f"获取合约名称成功: {address} → {contract_name}")
                                return contract_name

                    elif response.status == 429:
                        # 限流,切换密钥重试
                        api_key = self._get_api_key(chain)
                        params["apikey"] = api_key
                        await asyncio.sleep(0.5)
                        continue

            except asyncio.TimeoutError:
                logger.warning(f"获取合约名称超时 {address} (尝试{attempt+1}/{max_retries})")
                await asyncio.sleep(1)

            except Exception as e:
                logger.warning(f"获取合约名称错误 {address}: {e}")
                await asyncio.sleep(1)

        return None

    async def _fetch_contract_abi(
        self,
        session: aiohttp.ClientSession,
        address: str,
        chain: str
    ) -> Optional[str]:
        """获取合约ABI"""
        # 与_fetch_contract_name类似,这里简化实现
        api_key = self._get_api_key(chain)
        if not api_key:
            return None

        url = self.explorer_urls.get(chain)
        if not url:
            return None

        params = {
            "module": "contract",
            "action": "getabi",
            "address": address,
            "apikey": api_key
        }

        try:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("status") == "1":
                        return data.get("result")
        except:
            pass

        return None

    async def _check_if_erc20(
        self,
        session: aiohttp.ClientSession,
        address: str,
        chain: str
    ) -> bool:
        """
        检查是否为ERC20代币

        简化实现:基于是否有symbol/name方法
        """
        token_info = await self._fetch_token_info(session, address, chain)
        return token_info is not None and "symbol" in token_info

    async def _fetch_token_info(
        self,
        session: aiohttp.ClientSession,
        address: str,
        chain: str
    ) -> Optional[dict]:
        """
        通过Web3 RPC获取ERC20代币信息

        调用:
        - symbol()
        - name()
        - decimals()

        Returns:
            {symbol, name, decimals} 或 None(非ERC20合约)
        """
        # 获取对应链的Web3实例
        w3 = self.web3_instances.get(chain)
        if not w3:
            logger.debug(f"链{chain}的Web3实例不可用")
            return None

        # ERC20标准ABI(仅包含需要的方法)
        erc20_abi = [
            {
                "constant": True,
                "inputs": [],
                "name": "symbol",
                "outputs": [{"name": "", "type": "string"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "name",
                "outputs": [{"name": "", "type": "string"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [],
                "name": "decimals",
                "outputs": [{"name": "", "type": "uint8"}],
                "type": "function"
            }
        ]

        try:
            # 创建合约实例
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(address),
                abi=erc20_abi
            )

            # 使用asyncio在线程池中执行同步调用
            loop = asyncio.get_event_loop()

            # 并发调用三个方法
            symbol_task = loop.run_in_executor(None, contract.functions.symbol().call)
            name_task = loop.run_in_executor(None, contract.functions.name().call)
            decimals_task = loop.run_in_executor(None, contract.functions.decimals().call)

            # 等待结果
            symbol, name, decimals = await asyncio.gather(
                symbol_task, name_task, decimals_task,
                return_exceptions=True
            )

            # 检查是否有错误
            if isinstance(symbol, Exception) or isinstance(name, Exception) or isinstance(decimals, Exception):
                logger.debug(f"合约{address}不是标准ERC20: symbol={symbol}, name={name}, decimals={decimals}")
                return None

            logger.debug(f"获取ERC20信息成功: {address} → {symbol} ({name}), decimals={decimals}")

            return {
                "symbol": symbol,
                "name": name,
                "decimals": decimals
            }

        except ContractLogicError as e:
            logger.debug(f"合约{address}调用失败(可能不是ERC20): {e}")
            return None

        except Exception as e:
            logger.warning(f"获取ERC20信息错误 {address}: {e}")
            return None

    def _get_api_key(self, chain: str) -> Optional[str]:
        """获取指定链的可用API密钥"""
        # 映射chain到key pool名称
        key_pool_mapping = {
            "mainnet": "etherscan",
            "bsc": "bscscan",
            "arbitrum": "arbiscan",
            "optimism": "optimism_etherscan",
            "polygon": "polygonscan"
        }

        pool_name = key_pool_mapping.get(chain)
        if not pool_name or pool_name not in self.key_pools:
            return None

        return self.key_pools[pool_name].get_available_key()

    def _infer_semantic_type(
        self,
        contract_name: Optional[str],
        symbol: Optional[str]
    ) -> str:
        """
        推断合约的语义类型

        规则:
        - w[A-Z]\w+ → wrapped_token
        - \w+Pair → uniswap_v2_pair
        - \w+Pool → liquidity_pool
        - DPP → dodo_private_pool
        """
        name = contract_name or symbol or ""

        import re

        patterns = {
            r'^w[A-Z]\w+': 'wrapped_token',
            r'\w+Pair$': 'uniswap_v2_pair',
            r'\w+Pool$': 'liquidity_pool',
            r'^DPP': 'dodo_private_pool',
            r'Router': 'router',
            r'Factory': 'factory'
        }

        for pattern, semantic in patterns.items():
            if re.search(pattern, name):
                return semantic

        return "unknown"


# =============================================================================
# 工具函数
# =============================================================================

def sync_batch_fetch(addresses: List[str], chain: str = "mainnet") -> Dict[str, dict]:
    """
    同步包装器 - 方便在非异步代码中调用

    Args:
        addresses: 合约地址列表
        chain: 链名称

    Returns:
        {address: contract_info}
    """
    fetcher = OnChainDataFetcher.from_config("config/api_keys.json")
    return asyncio.run(fetcher.batch_fetch_contracts(addresses, chain))


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    # 测试地址列表(BarleyFinance示例)
    test_addresses = [
        "0x04c80Bb477890F3021F03B068238836Ee20aA0b8",  # wBARL
        "0x3e2324342bF5B8A1Dca42915f0489497203d640E",  # BARL
        "0x6B175474E89094C44Da98b954EedeAC495271d0F",  # DAI
    ]

    print("测试OnChainDataFetcher...")
    results = sync_batch_fetch(test_addresses, chain="mainnet")

    for addr, info in results.items():
        print(f"\n{addr}:")
        print(json.dumps(info, indent=2))
