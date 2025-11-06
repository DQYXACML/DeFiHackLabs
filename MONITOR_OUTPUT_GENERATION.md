# Monitor 输出文件生成指南

## 📖 什么是 Monitor 输出文件？

`autopath/barleyfinance_analysis.json` 是一个 **Go Monitor 程序**的输出文件，包含对攻击交易的运行时分析结果。

**文件内容：**
```json
{
  "project": "BarleyFinance_exp",
  "tx_hash": "0x995e...",
  "violations": [
    {
      "type": "balance_change_rate",
      "measured_value": 0.87,
      "threshold": 0.5
    }
  ],
  "runtime_data": {
    "gas_used": 2456789,
    "loop_iterations": {"0xbdbc91ab": 20}
  }
}
```

---

## 🚀 生成方式

### 方式 1: 使用 Go Monitor 真实生成（完整流程）

这是**真正的监控流程**，会在本地链上重放攻击并分析。

#### 步骤 1: 启动 Anvil 本地链

```bash
# 终端 1: 启动 Anvil（保持运行）
anvil --fork-url https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY \
      --fork-block-number 19106654 \
      --port 8545
```

**说明：**
- Fork 主网到攻击发生的区块
- BarleyFinance 攻击发生在区块 19106655，所以 fork 到前一个区块 19106654

#### 步骤 2: 部署攻击状态

```bash
# 终端 2: 部署状态（让链恢复到攻击前）
python src/test/deploy_to_anvil.py \
  --state-file extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json
```

**或者使用生成的部署脚本：**
```bash
cd generated_deploy
python script/2024-01/deploy_BarleyFinance_exp.py
```

#### 步骤 3: 编译 Go Monitor（首次使用需要）

```bash
cd autopath

# 下载依赖
go mod download

# 编译
go build -o monitor ./cmd/monitor
```

**编译完成后，你会看到：**
```bash
ls -lh monitor
# -rwxrwxr-x  1 dqy dqy 11M Oct 27 11:52 monitor
```

#### 步骤 4: 执行攻击并获取交易 Hash

```bash
# 终端 2: 运行攻击脚本
forge test \
  --match-path src/test/2024-01/BarleyFinance_exp.sol \
  --match-test testExploit \
  --rpc-url http://localhost:8545 \
  -vv
```

**从输出中获取交易 hash：**
```
[PASS] testExploit() (gas: 850234)
Traces:
  [850234] ExploiterContract::testExploit()
    ├─ [Transaction Hash: 0xabc123def456...]  ← 这个就是交易hash
```

**或从 Anvil 日志中查看：**
```
# Anvil 终端会显示
eth_sendRawTransaction
  Transaction: 0xabc123def456...
```

#### 步骤 5: 运行 Go Monitor 分析交易

```bash
cd autopath

# 方式 A: 使用交易 hash
./monitor \
  -rpc http://localhost:8545 \
  -tx 0xabc123def456... \
  -output barleyfinance_analysis.json \
  -v

# 方式 B: 使用项目名（会自动查找最新交易）
./monitor \
  -rpc http://localhost:8545 \
  -event BarleyFinance_exp \
  -output barleyfinance_analysis.json \
  -v
```

**Monitor 参数说明：**
- `-rpc`: Anvil RPC 地址
- `-tx`: 要分析的交易 hash
- `-event`: 项目名称（可选，会查找最新交易）
- `-output`: 输出文件路径
- `-v`: 详细输出

**执行后，会看到：**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
交易分析结果
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
区块号: 2
Gas使用: 850234
状态: 1

📞 函数调用统计:
  0xbdbc91ab: 20 次  (flash函数)

💰 余额变化:
  0x356E7481B957bE0165D6751a49b4b7194AEf18D5
    变化率: 87%

⚠️  [high] balance_change_rate 违规
   实际值: 0.87
   阈值: 0.5

[... 更多分析结果 ...]

✅ 分析完成，结果已保存到 barleyfinance_analysis.json
```

#### 步骤 6: 验证生成的文件

```bash
# 查看生成的文件
cat autopath/barleyfinance_analysis.json | jq '.' | head -50

# 检查违规数量
cat autopath/barleyfinance_analysis.json | jq '.violations | length'
# 应该输出: 6
```

---

### 方式 2: 创建测试数据（快速原型）

如果你只想测试不变量生成系统，不需要运行 Monitor，可以手动创建测试数据。

#### 创建 Mock Monitor 输出

```bash
# 创建测试文件
cat > autopath/barleyfinance_analysis.json << 'EOF'
{
  "project": "BarleyFinance_exp",
  "tx_hash": "0x995e880635f4a7462a420a58527023f946710167ea4c6c093d7d193062a33b01",
  "block_number": 19106655,
  "timestamp": "2025-10-28T06:52:00Z",
  "attack_detected": true,
  "violations": [
    {
      "invariant_id": "INV_001",
      "type": "balance_change_rate",
      "severity": "high",
      "description": "单次交易中合约余额变化率不应超过50%",
      "threshold": 0.5,
      "measured_value": 0.87,
      "reason": "观察到余额变化率为87%",
      "details": {
        "address": "0x356E7481B957bE0165D6751a49b4b7194AEf18D5",
        "balance_before": 1000000000000000000,
        "balance_after": 1870000000000000000,
        "change_rate": 0.87
      }
    },
    {
      "invariant_id": "INV_002",
      "type": "loop_iterations",
      "severity": "high",
      "description": "单个交易中循环迭代次数不应超过10次",
      "threshold": 10,
      "measured_value": 20,
      "reason": "观察到循环执行20次",
      "details": {
        "function_selector": "0xbdbc91ab",
        "iterations": 20,
        "pattern": "flash函数在循环中重复调用"
      }
    },
    {
      "invariant_id": "INV_003",
      "type": "flash_loan_depth",
      "severity": "critical",
      "description": "闪电贷嵌套深度不应超过1",
      "threshold": 1,
      "measured_value": 2,
      "reason": "观察到闪电贷嵌套深度为2",
      "details": {
        "flashloan_calls": 2,
        "in_loop": true,
        "callback_count": 1
      }
    }
  ],
  "runtime_data": {
    "gas_used": 2456789,
    "call_depth": 8,
    "loop_iterations": {
      "0xbdbc91ab": 20
    },
    "flashloan_depth": 2,
    "reentrancy_depth": 2,
    "function_calls": {
      "0xbdbc91ab": 20,
      "0xa515366a": 23
    },
    "balance_changes": {
      "0x356E7481B957bE0165D6751a49b4b7194AEf18D5": {
        "before": "1000000000000000000",
        "after": "1870000000000000000",
        "change_rate": 0.87
      }
    }
  },
  "summary": {
    "total_violations": 6,
    "critical_violations": 2,
    "high_violations": 3,
    "medium_violations": 1,
    "attack_vectors": [
      "Flashloan循环攻击",
      "重入漏洞利用",
      "余额操纵"
    ]
  }
}
EOF
```

**这就是我们当前使用的测试数据！**

---

## 📊 两种方式对比

| 特性 | 方式 1: 真实 Monitor | 方式 2: Mock 数据 |
|------|---------------------|------------------|
| **准确性** | ✅ 真实运行时数据 | ⚠️ 手动模拟数据 |
| **速度** | 慢（需要启动链、部署、执行） | 快（直接创建文件） |
| **复杂度** | 高（需要 Anvil + Go） | 低（只需文本编辑器） |
| **适用场景** | 真实验证、生产环境 | 快速原型、测试 |
| **数据完整性** | ✅ 完整的 trace 数据 | ⚠️ 可能缺少某些字段 |

---

## 🎯 推荐流程

### 对于开发/测试
```bash
# 使用 Mock 数据（方式 2）
# 已经有了 barleyfinance_analysis.json
python src/test/generate_invariants_from_monitor.py \
  --monitor-output autopath/barleyfinance_analysis.json \
  --output extracted_contracts/2024-01/BarleyFinance_exp/invariants.json
```

### 对于生产/验证
```bash
# 使用真实 Monitor（方式 1）
# 步骤 1-5 完整执行
./autopath/monitor -rpc http://localhost:8545 \
  -tx 0x... \
  -output autopath/barleyfinance_analysis.json

# 然后生成不变量
python src/test/generate_invariants_from_monitor.py \
  --monitor-output autopath/barleyfinance_analysis.json \
  --output extracted_contracts/2024-01/BarleyFinance_exp/invariants.json
```

---

## 🔍 Monitor 输出文件结构

### 完整结构说明

```json
{
  // === 基本信息 ===
  "project": "项目名称",
  "tx_hash": "交易哈希",
  "block_number": 19106655,
  "timestamp": "ISO8601时间戳",
  "attack_detected": true,

  // === 违规列表 ===
  "violations": [
    {
      "invariant_id": "INV_001",
      "type": "balance_change_rate | loop_iterations | flash_loan_depth | ...",
      "severity": "critical | high | medium | low",
      "description": "不变量描述",
      "threshold": 0.5,           // 阈值
      "measured_value": 0.87,     // 实测值
      "reason": "违规原因",
      "details": {                // 详细信息
        "address": "0x...",
        "balance_before": "1000000000000000000",
        "balance_after": "1870000000000000000"
      }
    }
  ],

  // === 运行时数据 ===
  "runtime_data": {
    "gas_used": 2456789,
    "call_depth": 8,
    "loop_iterations": {
      "0xbdbc91ab": 20          // 函数选择器 -> 循环次数
    },
    "flashloan_depth": 2,
    "reentrancy_depth": 2,
    "function_calls": {
      "0xbdbc91ab": 20,
      "0xa515366a": 23
    },
    "balance_changes": {
      "0x356E...": {
        "before": "1000000000000000000",
        "after": "1870000000000000000",
        "change_rate": 0.87
      }
    }
  },

  // === 汇总信息 ===
  "summary": {
    "total_violations": 6,
    "critical_violations": 2,
    "high_violations": 3,
    "medium_violations": 1,
    "attack_vectors": [
      "Flashloan循环攻击",
      "重入漏洞利用"
    ]
  }
}
```

---

## 🛠️ 快速命令参考

### 完整端到端流程（真实 Monitor）

```bash
# 1. 启动 Anvil
anvil --fork-url YOUR_RPC --fork-block-number 19106654 &

# 2. 部署状态
python src/test/deploy_to_anvil.py \
  --state-file extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json

# 3. 执行攻击（获取 tx hash）
forge test --match-path src/test/2024-01/BarleyFinance_exp.sol \
  --rpc-url http://localhost:8545 -vv | grep "Transaction Hash"

# 4. 运行 Monitor
cd autopath
./monitor -rpc http://localhost:8545 \
  -tx 0xTX_HASH_FROM_STEP_3 \
  -output barleyfinance_analysis.json \
  -v

# 5. 生成不变量
cd ..
python src/test/generate_invariants_from_monitor.py \
  --monitor-output autopath/barleyfinance_analysis.json \
  --output extracted_contracts/2024-01/BarleyFinance_exp/invariants.json
```

### 快速测试流程（Mock 数据）

```bash
# 已有 barleyfinance_analysis.json，直接生成不变量
python src/test/generate_invariants_from_monitor.py \
  --monitor-output autopath/barleyfinance_analysis.json \
  --output extracted_contracts/2024-01/BarleyFinance_exp/invariants.json
```

---

## 📚 相关文档

- **QUICKSTART.md**: 快速开始指南
- **STORAGE_INVARIANT_USAGE.md**: 完整使用文档
- **autopath/README.md**: Go Monitor 详细说明

---

**总结：**
- ✅ **方式 1（真实）**: 适合生产环境，需要完整的链和监控系统
- ✅ **方式 2（Mock）**: 适合开发测试，快速原型验证
- 🎯 **当前项目**: 使用方式 2 的 Mock 数据，已经可以正常运行！
