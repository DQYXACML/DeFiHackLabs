#!/usr/bin/env python3
"""
Anvil 进程管理工具

提供启动、停止和健康检查 Anvil 本地链的功能
"""

import subprocess
import time
import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AnvilManager:
    """Anvil 进程管理器"""

    def __init__(self, port: int = 8545, fork_url: Optional[str] = None, fork_block: Optional[int] = None):
        """
        初始化 Anvil 管理器

        Args:
            port: Anvil 监听端口
            fork_url: Fork 的 RPC URL（可选）
            fork_block: Fork 的区块号（可选）
        """
        self.port = port
        self.fork_url = fork_url
        self.fork_block = fork_block
        self.process: Optional[subprocess.Popen] = None
        self.rpc_url = f"http://localhost:{port}"

    def start(self, timeout: int = 30) -> bool:
        """
        启动 Anvil 进程

        Args:
            timeout: 启动超时时间（秒）

        Returns:
            是否启动成功
        """
        # 构建命令
        cmd = ["anvil", "--port", str(self.port), "--silent"]

        if self.fork_url:
            cmd.extend(["--fork-url", self.fork_url])
        if self.fork_block:
            cmd.extend(["--fork-block-number", str(self.fork_block)])

        logger.info(f"启动 Anvil (端口 {self.port})...")

        # 启动进程
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # 等待 Anvil 启动
        for i in range(timeout * 2):  # 每 0.5 秒检查一次
            if self._check_health():
                logger.info(f"✓ Anvil 已启动 (PID: {self.process.pid}, 端口: {self.port})")
                return True
            time.sleep(0.5)

        logger.error(f"Anvil 启动超时 ({timeout}秒)")
        self.stop()
        return False

    def stop(self):
        """停止 Anvil 进程"""
        if self.process:
            logger.info("停止 Anvil...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
                logger.info("✓ Anvil 已停止")
            except subprocess.TimeoutExpired:
                logger.warning("Anvil 未响应终止信号，强制杀死进程")
                self.process.kill()
                self.process.wait()
            self.process = None

    def _check_health(self) -> bool:
        """
        检查 Anvil 是否运行正常

        Returns:
            Anvil 是否可用
        """
        try:
            response = requests.post(
                self.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_blockNumber",
                    "params": [],
                    "id": 1
                },
                timeout=1
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def get_latest_block(self) -> int:
        """
        获取最新区块号

        Returns:
            区块号
        """
        response = requests.post(
            self.rpc_url,
            json={
                "jsonrpc": "2.0",
                "method": "eth_blockNumber",
                "params": [],
                "id": 1
            }
        )
        result = response.json()
        return int(result['result'], 16)

    def get_latest_transaction(self) -> Optional[str]:
        """
        获取最新交易的 hash

        Returns:
            交易 hash，如果没有交易则返回 None
        """
        response = requests.post(
            self.rpc_url,
            json={
                "jsonrpc": "2.0",
                "method": "eth_getBlockByNumber",
                "params": ["latest", True],
                "id": 1
            }
        )
        result = response.json()
        transactions = result['result']['transactions']

        if transactions:
            return transactions[-1]['hash']
        return None

    def __enter__(self):
        """上下文管理器：进入"""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器：退出"""
        self.stop()


def start_anvil(port: int = 8545, fork_url: Optional[str] = None, fork_block: Optional[int] = None) -> AnvilManager:
    """
    启动 Anvil 并返回管理器

    Args:
        port: Anvil 监听端口
        fork_url: Fork 的 RPC URL（可选）
        fork_block: Fork 的区块号（可选）

    Returns:
        AnvilManager 实例
    """
    manager = AnvilManager(port, fork_url, fork_block)
    if not manager.start():
        raise RuntimeError("无法启动 Anvil")
    return manager


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    print("测试 1: 启动空白 Anvil")
    with AnvilManager(port=8545) as anvil:
        print(f"  当前区块: {anvil.get_latest_block()}")
        time.sleep(2)

    print("\n测试 2: 启动 Fork 主网的 Anvil")
    with AnvilManager(
        port=8545,
        fork_url="https://eth-mainnet.g.alchemy.com/v2/oKxs-03sij-U_N0iOlrSsZFr29-IqbuF",
        fork_block=19106654
    ) as anvil:
        print(f"  当前区块: {anvil.get_latest_block()}")
        time.sleep(2)

    print("\n✓ 所有测试通过")
