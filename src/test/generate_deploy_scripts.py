#!/usr/bin/env python3
"""
Foundry部署脚本生成器

功能：
1. 遍历extracted_contracts目录
2. 读取attack_state.json
3. 生成Foundry部署脚本，使用vm.etch()在原地址部署
4. 恢复storage状态和ETH余额

作者: Claude Code
版本: 1.0.0
"""

import json
import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from web3 import Web3

# ============================================================================
# 配置
# ============================================================================

# 日志配置
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# 路径配置
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
EXTRACTED_DIR = PROJECT_ROOT / 'extracted_contracts'
OUTPUT_DIR = PROJECT_ROOT / 'generated_deploy'

# Solidity配置
MAX_INLINE_BYTECODE = 24000  # Solidity字面量大小限制
CHUNK_SIZE = 20000  # 超大bytecode分块大小

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ContractState:
    """合约状态"""
    address: str
    name: str
    balance_wei: str
    code: str
    code_size: int
    is_contract: bool
    storage: Dict[str, str]
    nonce: int

@dataclass
class EventState:
    """事件状态"""
    month: str
    event_name: str
    chain: str
    block_number: int
    timestamp: int
    contracts: List[ContractState]

@dataclass
class GenerationStats:
    """生成统计"""
    total_events: int = 0
    successful: int = 0
    failed: int = 0
    total_contracts: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

# ============================================================================
# Solidity代码生成器
# ============================================================================

class SolidityScriptGenerator:
    """Solidity部署脚本生成器"""

    SCRIPT_TEMPLATE = '''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Script.sol";

/**
 * @title {contract_name}
 * @notice 部署脚本 - {event_name}
 * @dev 从attack_state.json生成
 *
 * ⚠️ 注意: 此脚本仅用于测试环境
 * - 使用 vm.etch() 等 cheatcodes，只在 forge test 中有效
 * - 不能用于 forge script --broadcast
 * - 要部署到本地 anvil，请使用 Python 脚本:
 *   python deploy_to_anvil.py {event_name}
 *
 * 事件信息:
 * - 链: {chain}
 * - 区块: {block_number}
 * - 时间戳: {timestamp}
 * - 合约数量: {contract_count}
 *
 * 生成时间: {generated_at}
 */
contract {contract_name} is Script {{
    function run() external {{
        console.log(unicode"开始部署 {event_name} 状态...");

{deploy_code}

        console.log(unicode"部署完成！共 {contract_count} 个地址");
    }}
}}
'''

    PYTHON_DEPLOY_TEMPLATE = '''#!/usr/bin/env python3
"""
部署 {event_name} 攻击状态到本地 Anvil

事件信息:
- 链: {chain}
- 区块: {block_number}
- 时间戳: {timestamp}
- 合约数量: {contract_count}

生成时间: {generated_at}
"""

import json
import sys
from pathlib import Path
from web3 import Web3

def deploy_to_anvil(rpc_url: str = "http://localhost:8545"):
    """部署状态到 anvil"""

    # 连接到 anvil
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print(f"❌ 无法连接到 {{rpc_url}}")
        return False

    print(f"✓ 已连接到 {{rpc_url}}")
    print(f"\\n部署 {event_name} 攻击状态")
    print(f"  链: {chain}")
    print(f"  区块: {block_number}")
    print(f"  地址数量: {contract_count}")
    print()

    # 读取状态文件
    state_file = Path(__file__).parent.parent.parent.parent / "extracted_contracts" / "{month}" / "{event_name}" / "attack_state.json"
    if not state_file.exists():
        print(f"❌ 状态文件不存在: {{state_file}}")
        return False

    with open(state_file, 'r') as f:
        state = json.load(f)

    addresses = state['addresses']

    # 部署每个地址的状态
    for addr, data in addresses.items():
        print(f"处理 {{addr}}...")

        # 1. 设置代码
        if data['code'] and data['code'] != '0x':
            w3.provider.make_request('anvil_setCode', [addr, data['code']])
            print(f"  ✓ 设置代码: {{len(data['code'])//2}} bytes")

        # 2. 设置余额
        balance_hex = hex(int(data['balance_wei']))
        w3.provider.make_request('anvil_setBalance', [addr, balance_hex])
        if data['balance_wei'] != "0":
            print(f"  ✓ 设置余额: {{data['balance_wei']}} wei")

        # 3. 设置 storage
        if data['storage']:
            for slot, value in data['storage'].items():
                slot_hex = hex(int(slot))
                if not value.startswith('0x'):
                    value = '0x' + value
                w3.provider.make_request('anvil_setStorageAt', [addr, slot_hex, value])
            print(f"  ✓ 设置 storage: {{len(data['storage'])}} slots")

        # 4. 设置 nonce
        if data['nonce'] > 0:
            nonce_hex = hex(data['nonce'])
            w3.provider.make_request('anvil_setNonce', [addr, nonce_hex])
            print(f"  ✓ 设置 nonce: {{data['nonce']}}")

    print(f"\\n✅ 部署完成！共 {{len(addresses)}} 个地址")

    # 验证部署
    print("\\n验证部署:")
    sample_addrs = list(addresses.keys())[:3]
    for addr in sample_addrs:
        addr_checksum = w3.to_checksum_address(addr)
        balance = w3.eth.get_balance(addr_checksum)
        code_size = len(w3.eth.get_code(addr_checksum))
        print(f"  {{addr_checksum}}: balance={{balance}} wei, code={{code_size}} bytes")

    return True

if __name__ == '__main__':
    rpc_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8545"
    success = deploy_to_anvil(rpc_url)
    sys.exit(0 if success else 1)
'''

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.SolidityScriptGenerator')

    @staticmethod
    def _to_checksum(address: str) -> str:
        """转换地址为EIP-55校验和格式"""
        # 移除0x前缀（如果有）
        if address.startswith('0x') or address.startswith('0X'):
            address = address[2:]

        # 确保地址是小写
        address = address.lower()

        # 使用Web3转换为校验和格式
        return Web3.to_checksum_address('0x' + address)

    def generate_script(self, event: EventState) -> str:
        """
        生成部署脚本

        Args:
            event: 事件状态

        Returns:
            Solidity脚本内容
        """
        # 生成合约名称（移除特殊字符）
        contract_name = self._sanitize_contract_name(
            f"Deploy{event.event_name.replace('_exp', '')}"
        )

        # 生成部署代码
        deploy_code = self._generate_deploy_code(event.contracts)

        # 填充模板
        script = self.SCRIPT_TEMPLATE.format(
            contract_name=contract_name,
            event_name=event.event_name,
            chain=event.chain,
            block_number=event.block_number,
            timestamp=event.timestamp,
            contract_count=len(event.contracts),
            generated_at=datetime.now().isoformat(),
            deploy_code=deploy_code
        )

        return script

    def generate_python_script(self, event: EventState, month: str) -> str:
        """
        生成 Python 部署脚本

        Args:
            event: 事件状态
            month: 月份目录名

        Returns:
            Python脚本内容
        """
        # 填充模板
        script = self.PYTHON_DEPLOY_TEMPLATE.format(
            event_name=event.event_name,
            month=month,
            chain=event.chain,
            block_number=event.block_number,
            timestamp=event.timestamp,
            contract_count=len(event.contracts),
            generated_at=datetime.now().isoformat()
        )

        return script

    def _generate_deploy_code(self, contracts: List[ContractState]) -> str:
        """生成部署代码块"""
        lines = []

        # 第一步：部署所有合约代码
        lines.append("        // ========== 第1步: 部署合约代码 ==========")
        for i, contract in enumerate(contracts, 1):
            addr = self._to_checksum(contract.address)
            lines.append(f"        // [{i}/{len(contracts)}] {contract.name} ({addr})")

            if contract.is_contract and contract.code_size > 0:
                # 处理bytecode
                code_lines = self._generate_etch_code(addr, contract.code)
                lines.extend(code_lines)
            else:
                # EOA地址，无代码
                lines.append(f"        // EOA地址，无合约代码")

            lines.append("")

        # 第二步：恢复storage状态
        storage_contracts = [c for c in contracts if c.storage]
        if storage_contracts:
            lines.append("        // ========== 第2步: 恢复Storage状态 ==========")
            for contract in storage_contracts:
                addr = self._to_checksum(contract.address)
                lines.append(f"        // {contract.name} ({addr})")
                for slot, value in contract.storage.items():
                    # 确保value有0x前缀
                    if not value.startswith('0x'):
                        value = '0x' + value
                    lines.append(
                        f"        vm.store({addr}, "
                        f"bytes32(uint256({slot})), {value});"
                    )
                lines.append("")

        # 第三步：设置ETH余额
        lines.append("        // ========== 第3步: 设置ETH余额 ==========")
        for contract in contracts:
            addr = self._to_checksum(contract.address)
            if contract.balance_wei != "0":
                lines.append(
                    f"        vm.deal({addr}, {contract.balance_wei}); "
                    f"// {contract.name}"
                )

        # 第四步：设置nonce（对于EOA）
        eoa_contracts = [c for c in contracts if not c.is_contract and c.nonce > 0]
        if eoa_contracts:
            lines.append("")
            lines.append("        // ========== 第4步: 设置Nonce ==========")
            for contract in eoa_contracts:
                addr = self._to_checksum(contract.address)
                lines.append(
                    f"        vm.setNonce({addr}, {contract.nonce}); "
                    f"// {contract.name}"
                )

        # 第五步：标记地址
        lines.append("")
        lines.append("        // ========== 第5步: 标记地址 ==========")
        for contract in contracts:
            addr = self._to_checksum(contract.address)
            lines.append(f"        vm.label({addr}, \"{contract.name}\");")

        return "\n".join(lines)

    def _generate_etch_code(self, address: str, code_hex: str) -> List[str]:
        """生成vm.etch代码"""
        lines = []

        # 移除0x前缀
        if code_hex.startswith('0x'):
            code_hex = code_hex[2:]

        code_size = len(code_hex) // 2  # 字节大小

        if code_size == 0:
            lines.append(f"        vm.etch({address}, \"\");")
        elif code_size * 2 <= MAX_INLINE_BYTECODE:
            # 小型bytecode，直接内联
            lines.append(f"        vm.etch({address}, hex\"{code_hex}\");")
        else:
            # 超大bytecode，分块拼接
            # 使用地址的一部分作为变量名后缀，确保唯一性
            var_suffix = address[-8:]  # 取地址最后8个字符
            lines.append(f"        // 大型合约 ({code_size} bytes)，分块部署")
            lines.append(f"        bytes memory code{var_suffix} = hex\"{code_hex[:CHUNK_SIZE]}\";")

            remaining = code_hex[CHUNK_SIZE:]
            while remaining:
                chunk = remaining[:CHUNK_SIZE]
                remaining = remaining[CHUNK_SIZE:]
                lines.append(f"        code{var_suffix} = bytes.concat(code{var_suffix}, hex\"{chunk}\");")

            lines.append(f"        vm.etch({address}, code{var_suffix});")

        return lines

    def _sanitize_contract_name(self, name: str) -> str:
        """清理合约名称"""
        # 移除特殊字符，保留字母数字和下划线
        name = re.sub(r'[^a-zA-Z0-9_]', '', name)
        # 确保首字符是字母
        if name and not name[0].isalpha():
            name = 'C' + name
        return name or 'DeployScript'

# ============================================================================
# 部署脚本生成器
# ============================================================================

class DeployScriptGenerator:
    """部署脚本生成主控制器"""

    def __init__(self, extracted_dir: Path, output_dir: Path):
        self.extracted_dir = extracted_dir
        self.output_dir = output_dir
        self.script_generator = SolidityScriptGenerator()
        self.stats = GenerationStats()
        self.logger = logging.getLogger(__name__ + '.DeployScriptGenerator')

        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 初始化独立的 Foundry 项目结构
        self._setup_foundry_project()

    def _setup_foundry_project(self):
        """设置独立的 Foundry 项目结构"""
        # 创建 script 目录用于存放生成的脚本
        script_dir = self.output_dir / "script"
        script_dir.mkdir(exist_ok=True)

        # 创建 foundry.toml 配置文件
        foundry_toml_path = self.output_dir / "foundry.toml"
        if not foundry_toml_path.exists():
            foundry_toml_content = """[profile.default]
src = 'script'
out = 'out'
libs = ['../lib']
solc_version = '0.8.28'
test = 'test'
"""
            foundry_toml_path.write_text(foundry_toml_content)
            self.logger.info(f"创建 foundry.toml: {foundry_toml_path}")

        # 创建 remappings.txt（如果需要）
        remappings_path = self.output_dir / "remappings.txt"
        if not remappings_path.exists():
            remappings_content = """forge-std/=../lib/forge-std/src/
"""
            remappings_path.write_text(remappings_content)
            self.logger.info(f"创建 remappings.txt: {remappings_path}")

        # 创建 README
        readme_path = self.output_dir / "README.md"
        if not readme_path.exists():
            readme_content = """# Attack State Deployment Scripts

This directory contains auto-generated Foundry deployment scripts for reproducing attack states.

## ⚠️ Important

The generated scripts use Foundry's `vm.etch()`, `vm.store()`, and other cheatcodes. These only work in **test environments**, NOT with `forge script --broadcast`.

## Usage

### Method 1: Use in Tests (Recommended)

```solidity
// test/MyAttackTest.t.sol
import "forge-std/Test.sol";
import "../script/2024-01/BarleyFinance_exp_Deploy.s.sol";

contract MyAttackTest is Test {
    function setUp() public {
        // Deploy attack state in setUp
        new DeployBarleyFinance().run();
    }

    function testExploit() public {
        // Reproduce attack or test firewall here
        // All contracts and states are ready
    }
}
```

Run tests:
```bash
cd generated_deploy
forge test --match-path test/MyAttackTest.t.sol -vv
```

### Method 2: Verify Deployment

```bash
forge test --match-path test/VerifyDeploy.t.sol -vv
```

## Structure

- `script/<month>/` - Monthly organized deployment scripts
- `script/DeployAll.s.sol` - Master deployment script
- `test/` - Test examples
- `foundry.toml` - Isolated configuration

## Notes

- Scripts use `vm.etch()` to deploy contracts at original addresses
- Storage states are restored using `vm.store()`
- ETH balances are set using `vm.deal()`
- EOA nonces are set using `vm.setNonce()`
- **These cheatcodes only work in forge test, not in forge script --broadcast**

## Why Not forge script --broadcast?

- `vm.etch()` and other cheatcodes are testing tools, they don't generate real transactions
- These cheatcodes only work in forge test's EVM environment
- For real deployment, use other methods (e.g., Python + web3.py)

Generated by: `src/test/generate_deploy_scripts.py`
"""
            readme_path.write_text(readme_content)
            self.logger.info(f"创建 README.md: {readme_path}")

    def generate_all(self, date_filters: Optional[List[str]] = None,
                    limit: Optional[int] = None):
        """
        生成所有部署脚本

        Args:
            date_filters: 日期过滤器列表
            limit: 限制处理数量
        """
        self.logger.info("=" * 80)
        self.logger.info("开始生成部署脚本")
        self.logger.info("=" * 80)

        # 查找所有事件
        events = self._find_all_events(date_filters)
        self.stats.total_events = len(events)

        if limit:
            events = events[:limit]
            self.logger.info(f"限制处理前 {limit} 个事件")

        self.logger.info(f"找到 {len(events)} 个攻击事件")

        # 生成脚本列表（用于DeployAll）
        deploy_scripts = []

        # 处理每个事件
        for i, (month, event_name, event_dir) in enumerate(events, 1):
            self.logger.info(f"\n[{i}/{len(events)}] 处理: {month}/{event_name}")

            try:
                script_path = self._process_event(month, event_name, event_dir)
                if script_path:
                    self.stats.successful += 1
                    # 生成合约名称（与SolidityScriptGenerator._sanitize_contract_name保持一致）
                    contract_name = self.script_generator._sanitize_contract_name(
                        f"Deploy{event_name.replace('_exp', '')}"
                    )
                    deploy_scripts.append((month, event_name, contract_name))
                    self.logger.info(f"  ✓ 成功: {script_path.name}")
                else:
                    self.stats.failed += 1
                    self.logger.warning(f"  ✗ 失败")

            except Exception as e:
                error_msg = f"处理事件失败 {month}/{event_name}: {e}"
                self.logger.error(f"  ✗ {e}")
                self.stats.errors.append(error_msg)
                self.stats.failed += 1

        # 生成DeployAll脚本
        if deploy_scripts:
            self._generate_deploy_all(deploy_scripts)

        # 打印统计
        self._print_summary()

    def _find_all_events(self, date_filters: Optional[List[str]] = None) -> List:
        """查找所有事件目录"""
        events = []

        if not self.extracted_dir.exists():
            self.logger.error(f"提取目录不存在: {self.extracted_dir}")
            return events

        # 遍历月份目录
        for month_dir in sorted(self.extracted_dir.iterdir()):
            if not month_dir.is_dir():
                continue

            # 匹配 YYYY-MM 格式
            if not re.match(r'\d{4}-\d{2}', month_dir.name):
                continue

            # 应用过滤器
            if date_filters and not any(month_dir.name.startswith(f) for f in date_filters):
                continue

            # 遍历事件目录
            for event_dir in sorted(month_dir.iterdir()):
                if not event_dir.is_dir():
                    continue

                # 检查是否有attack_state.json
                state_file = event_dir / 'attack_state.json'
                if state_file.exists():
                    events.append((month_dir.name, event_dir.name, event_dir))

        return events

    def _process_event(self, month: str, event_name: str,
                      event_dir: Path) -> Optional[Path]:
        """
        处理单个事件

        Returns:
            生成的脚本路径或None
        """
        # 读取状态文件
        state_file = event_dir / 'attack_state.json'
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                state_data = json.load(f)
        except Exception as e:
            self.logger.error(f"  读取状态文件失败: {e}")
            return None

        # 解析状态
        event_state = self._parse_state(month, event_name, state_data)
        if not event_state:
            return None

        self.logger.info(f"  链: {event_state.chain}, 区块: {event_state.block_number}")
        self.logger.info(f"  合约数量: {len(event_state.contracts)}")
        self.stats.total_contracts += len(event_state.contracts)

        # 生成 Solidity 脚本
        script_content = self.script_generator.generate_script(event_state)

        # 保存 Solidity 脚本到 script/ 子目录
        output_month_dir = self.output_dir / "script" / month
        output_month_dir.mkdir(parents=True, exist_ok=True)

        script_path = output_month_dir / f"{event_name}_Deploy.s.sol"

        try:
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(script_content)
        except Exception as e:
            self.logger.error(f"  保存 Solidity 脚本失败: {e}")
            return None

        # 生成 Python 部署脚本
        python_content = self.script_generator.generate_python_script(event_state, month)
        python_path = output_month_dir / f"deploy_{event_name}.py"

        try:
            with open(python_path, 'w', encoding='utf-8') as f:
                f.write(python_content)
            # 设置可执行权限
            python_path.chmod(0o755)
        except Exception as e:
            self.logger.error(f"  保存 Python 脚本失败: {e}")

        return script_path

    def _parse_state(self, month: str, event_name: str,
                    state_data: Dict) -> Optional[EventState]:
        """解析状态数据"""
        try:
            metadata = state_data['metadata']
            addresses = state_data['addresses']

            contracts = []
            for address, info in addresses.items():
                contract = ContractState(
                    address=address,
                    name=info.get('name', 'Unknown'),
                    balance_wei=info.get('balance_wei', '0'),
                    code=info.get('code', ''),
                    code_size=info.get('code_size', 0),
                    is_contract=info.get('is_contract', False),
                    storage=info.get('storage', {}),
                    nonce=info.get('nonce', 0)
                )
                contracts.append(contract)

            return EventState(
                month=month,
                event_name=event_name,
                chain=metadata['chain'],
                block_number=metadata['block_number'],
                timestamp=metadata['timestamp'],
                contracts=contracts
            )

        except Exception as e:
            self.logger.error(f"  解析状态失败: {e}")
            return None

    def _generate_deploy_all(self, deploy_scripts: List):
        """生成DeployAll总控脚本"""
        self.logger.info("\n生成DeployAll总控脚本...")

        # 生成import语句
        imports = []
        run_calls = []

        for month, event_name, script_name in deploy_scripts:
            # 构建相对导入路径（script目录下的相对路径）
            import_path = f"./{month}/{event_name}_Deploy.s.sol"
            imports.append(f'import "{import_path}";')
            run_calls.append(f"        new {script_name}().run();")

        script_content = f'''// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "forge-std/Script.sol";
{chr(10).join(imports)}

/**
 * @title DeployAll
 * @notice 部署所有攻击事件的状态
 * @dev 自动生成的总控脚本
 *
 * 统计信息:
 * - 总事件数: {len(deploy_scripts)}
 * - 生成时间: {datetime.now().isoformat()}
 */
contract DeployAll is Script {{
    function run() external {{
        console.log(unicode"开始部署所有攻击状态...");
        console.log(unicode"总计: {len(deploy_scripts)} 个事件");
        console.log("");

{chr(10).join(run_calls)}

        console.log("");
        console.log(unicode"所有部署完成！");
    }}
}}
'''

        # 保存脚本到 script/ 目录
        deploy_all_path = self.output_dir / 'script' / 'DeployAll.s.sol'
        with open(deploy_all_path, 'w', encoding='utf-8') as f:
            f.write(script_content)

        self.logger.info(f"  ✓ DeployAll脚本: {deploy_all_path}")

    def _print_summary(self):
        """打印统计摘要"""
        self.logger.info("\n" + "=" * 80)
        self.logger.info("生成摘要")
        self.logger.info("=" * 80)
        self.logger.info(f"总事件数:        {self.stats.total_events}")
        self.logger.info(f"成功:            {self.stats.successful}")
        self.logger.info(f"失败:            {self.stats.failed}")
        self.logger.info(f"总合约数:        {self.stats.total_contracts}")
        self.logger.info(f"\n输出目录:        {self.output_dir}")

        if self.stats.errors:
            self.logger.info(f"错误数:          {len(self.stats.errors)}")

        self.logger.info("=" * 80)

# ============================================================================
# 命令行接口
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Foundry部署脚本生成器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 生成所有事件的部署脚本
  python src/test/generate_deploy_scripts.py

  # 只生成2024-01的脚本
  python src/test/generate_deploy_scripts.py --filter 2024-01

  # 测试模式（只生成前5个）
  python src/test/generate_deploy_scripts.py --limit 5
        """
    )

    parser.add_argument(
        '--filter',
        dest='filters',
        action='append',
        help='日期过滤器（可重复使用）'
    )

    parser.add_argument(
        '--limit',
        type=int,
        help='限制处理数量（用于测试）'
    )

    parser.add_argument(
        '--output',
        type=Path,
        default=OUTPUT_DIR,
        help=f'输出目录（默认: {OUTPUT_DIR}）'
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

    # 检查extracted_contracts目录
    if not EXTRACTED_DIR.exists():
        logger.error(f"未找到提取目录: {EXTRACTED_DIR}")
        return 1

    # 创建生成器
    generator = DeployScriptGenerator(
        extracted_dir=EXTRACTED_DIR,
        output_dir=args.output
    )

    # 执行生成
    try:
        generator.generate_all(
            date_filters=args.filters,
            limit=args.limit
        )
        return 0
    except KeyboardInterrupt:
        logger.info("\n\n用户中断")
        generator._print_summary()
        return 1

if __name__ == '__main__':
    exit(main())
