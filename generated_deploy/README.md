# Attack State Deployment Scripts

自动生成的攻击状态部署脚本，支持部署到本地 Anvil 节点。

## 📁 目录结构

```
generated_deploy/
├── script/
│   ├── 2024-01/
│   │   ├── BarleyFinance_exp_Deploy.s.sol    # Solidity脚本（仅用于测试）
│   │   └── deploy_BarleyFinance_exp.py       # Python部署脚本（部署到Anvil）
│   └── DeployAll.s.sol
├── test/
│   └── VerifyDeploy.t.sol                     # 验证测试
├── foundry.toml
└── README.md
```

## 🚀 使用方法

### 方式1: Python脚本部署到Anvil（推荐）

**适用场景**: 将攻击状态真正部署到本地 Anvil 链上

```bash
# 1. 启动 Anvil
anvil --block-base-fee-per-gas 0 --gas-price 0

# 2. 运行Python部署脚本
cd generated_deploy
python script/2024-01/deploy_BarleyFinance_exp.py

# 3. 验证部署
cast code 0x356E7481B957bE0165D6751a49b4b7194AEf18D5 --rpc-url http://localhost:8545
cast balance 0x7B3a6EFF1C9925e509C2b01A389238c1FCC462B6 --rpc-url http://localhost:8545
```

**输出示例**:
```
✓ 已连接到 http://localhost:8545

部署 BarleyFinance_exp 攻击状态
  链: mainnet
  区块: 19106654
  地址数量: 7

处理 0x7b3a6eff1c9925e509c2b01a389238c1fcc462b6...
  ✓ 设置余额: 1406062464485437940 wei
  ✓ 设置 nonce: 10
...
✅ 部署完成！共 7 个地址

验证部署:
  0x7B3a6EFF1C9925e509C2b01A389238c1FCC462B6: balance=1406062464485437940 wei
  0x356E7481B957bE0165D6751a49b4b7194AEf18D5: code=4252 bytes
```

### 方式2: Solidity脚本（仅测试环境）

**适用场景**: 在 Foundry 测试中使用

```solidity
// test/MyAttackTest.t.sol
import "forge-std/Test.sol";
import "../script/2024-01/BarleyFinance_exp_Deploy.s.sol";

contract MyAttackTest is Test {
    function setUp() public {
        // 在测试环境中部署状态
        new DeployBarleyFinance().run();
    }

    function testExploit() public {
        // 重现攻击或测试防火墙
        address attacker = 0x7B3a6EFF1C9925e509C2b01A389238c1FCC462B6;
        assertEq(attacker.balance, 1406062464485437940);
    }
}
```

运行测试:
```bash
cd generated_deploy
forge test --match-path test/MyAttackTest.t.sol -vv
```

## 📊 Python vs Solidity 对比

| 特性 | Python脚本 | Solidity脚本 |
|------|-----------|-------------|
| 部署到Anvil | ✅ 真实部署 | ❌ 仅模拟 |
| 使用场景 | 本地测试、重现攻击 | forge test环境 |
| 生成交易 | ❌ 直接修改状态 | ❌ 使用cheatcodes |
| 验证便利性 | ✅ 可用cast验证 | ✅ 测试内验证 |
| 推荐用途 | **部署到Anvil** | forge test中使用 |

## 🛠️ 工作原理

### Python脚本原理

使用 Anvil 的 RPC 方法直接设置状态：

```python
# 1. 设置合约代码
w3.provider.make_request('anvil_setCode', [address, bytecode])

# 2. 设置余额
w3.provider.make_request('anvil_setBalance', [address, balance_hex])

# 3. 设置storage
w3.provider.make_request('anvil_setStorageAt', [address, slot_hex, value])

# 4. 设置nonce
w3.provider.make_request('anvil_setNonce', [address, nonce_hex])
```

### Solidity脚本原理

使用 Foundry 的 cheatcodes（仅在测试中有效）：

```solidity
vm.etch(address, bytecode);        // 部署代码
vm.store(address, slot, value);    // 设置storage
vm.deal(address, balance);         // 设置余额
vm.setNonce(address, nonce);       // 设置nonce
```

## 🔧 生成更多脚本

```bash
# 回到项目根目录
cd /home/dqy/Firewall/FirewallOnchain/DeFiHackLabs

# 生成所有事件的部署脚本
python src/test/generate_deploy_scripts.py

# 生成特定月份
python src/test/generate_deploy_scripts.py --filter 2024-01

# 限制数量
python src/test/generate_deploy_scripts.py --limit 10
```

## ⚠️ 重要提示

1. **Python脚本仅适用于Anvil**: 这些RPC方法是Anvil特有的，不能用于其他节点
2. **Solidity脚本不能broadcast**: `vm.etch()`等cheatcodes不生成真实交易
3. **路径依赖**: Python脚本依赖`extracted_contracts/`目录中的`attack_state.json`

## 📝 示例工作流

```bash
# 1. 启动Anvil
anvil > /tmp/anvil.log 2>&1 &

# 2. 部署攻击状态
python script/2024-01/deploy_BarleyFinance_exp.py

# 3. 运行攻击重现或测试防火墙
forge script test/Lodestar/scripts/ExploitLocal.s.sol --rpc-url http://localhost:8545 --broadcast

# 4. 验证结果
cast call 0x... "balanceOf(address)" "0x..." --rpc-url http://localhost:8545
```

---

生成时间: 2025-10-26  
生成工具: `src/test/generate_deploy_scripts.py`
