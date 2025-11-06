# 存储级不变量生成 - 完整执行流程

## 以 BarleyFinance_exp 为例的完整流程

---

## 📋 前提条件

### 1. 必需的工具
```bash
# 检查 Python 环境
python --version  # 需要 Python 3.8+

# 检查 Foundry 工具链
forge --version
anvil --version
cast --version

# 检查 Go（用于运行 monitor）
go version  # 如果要用 Go monitor
```

### 2. 必需的文件
- ✅ 攻击合约: `src/test/2024-01/BarleyFinance_exp.sol`
- ✅ 接口文件: `src/test/interface.sol`

---

## 🚀 完整执行流程

### 步骤 1: 启动 Anvil 本地链

```bash
# 终端 1: 启动 Anvil（保持运行）
anvil --fork-url https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY \
      --fork-block-number 19106654 \
      --port 8545
```

**说明：**
- `--fork-url`: 使用主网 RPC（可以用 Infura/Alchemy/Quicknode）
- `--fork-block-number`: BarleyFinance 攻击发生在区块 19106654
- `--port`: 监听端口 8545

**验证 Anvil 是否运行：**
```bash
# 终端 2
netstat -tuln | grep 8545
# 或
cast block-number --rpc-url http://localhost:8545
```

---

### 步骤 2: 收集攻击状态（生成 attack_state.json）

```bash
# 终端 2: 运行状态收集脚本
python src/test/collect_attack_states.py \
  --filter BarleyFinance_exp \
  --debug

# 或者收集整个 2024-01 目录
python src/test/collect_attack_states.py \
  --filter 2024-01 \
  --limit 5
```

**输出位置：**
```
extracted_contracts/2024-01/BarleyFinance_exp/
├── attack_state.json          ← 生成的状态文件
├── addresses.json
└── [各个合约的 sol 文件]
```

**验证状态文件：**
```bash
# 检查文件是否存在
ls -lh extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json

# 查看文件内容概要
cat extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json | jq '.metadata'
```

**预期输出：**
```json
{
  "chain": "mainnet",
  "block_number": 19106654,
  "total_addresses": 7,
  "collected_addresses": 7,
  "collection_method": "trace",
  "attack_tx_hash": "0x995e880635f4a7462a420a58527023f946710167ea4c6c093d7d193062a33b01"
}
```

---

### 步骤 3: 运行 Go Monitor（可选，生成 monitor 输出）

**选项 A: 使用现有的 mock 数据（快速测试）**
```bash
# 我们已经有了测试用的 mock 数据
ls autopath/barleyfinance_analysis.json
```

**选项 B: 运行真实的 Go Monitor**
```bash
# 如果你有 Go monitor 编译好的二进制
cd autopath
./monitor \
  -rpc http://localhost:8545 \
  -tx 0x995e880635f4a7462a420a58527023f946710167ea4c6c093d7d193062a33b01 \
  -output barleyfinance_analysis.json \
  -v
```

**Monitor 输出格式：**
```json
{
  "project": "BarleyFinance_exp",
  "tx_hash": "0x995e...",
  "violations": [
    {
      "invariant_id": "INV_001",
      "type": "balance_change_rate",
      "measured_value": 0.87,
      "threshold": 0.5
    }
  ],
  "runtime_data": {
    "gas_used": 2456789,
    "call_depth": 8,
    "loop_iterations": { "0xbdbc91ab": 20 }
  }
}
```

---

### 步骤 4: 生成不变量（执行级 + 存储级）

```bash
# 终端 2: 运行不变量生成脚本
python src/test/generate_invariants_from_monitor.py \
  --monitor-output autopath/barleyfinance_analysis.json \
  --output extracted_contracts/2024-01/BarleyFinance_exp/invariants.json \
  --project BarleyFinance_exp
```

**脚本执行流程：**
```
[1/4] 解析 monitor 输出
  ↓ 读取 barleyfinance_analysis.json
  ↓ 提取 violations 数据

[2/4] 生成执行级不变量
  ↓ 基于 violations 生成 6 个执行级不变量

[3/4] 生成存储级不变量
  ↓ 自动加载 extracted_contracts/.../attack_state.json
  ↓ 分析存储槽语义
  ↓ 检测协议类型（Vault）
  ↓ 发现存储关系
  ↓ 生成 4 个存储级不变量

[4/4] 保存结果
  ↓ 写入 invariants.json
```

**预期输出：**
```
================================================================================
✓ 成功生成 10 个不变量
  - 执行级: 6
  - 存储级: 4
================================================================================
```

---

### 步骤 5: 查看和分析结果

#### 5.1 查看生成的文件
```bash
ls -lh extracted_contracts/2024-01/BarleyFinance_exp/invariants.json
```

#### 5.2 查看所有存储级不变量
```bash
cat extracted_contracts/2024-01/BarleyFinance_exp/invariants.json | \
  jq '.storage_invariants[] | {id, type, severity, description}'
```

**预期输出：**
```json
{
  "id": "SINV_001",
  "type": "share_price_stability",
  "severity": "critical",
  "description": "Vault share price must not change more than 5% per transaction"
}
{
  "id": "SINV_002",
  "type": "supply_backing_consistency",
  "severity": "critical",
  "description": "Total supply must be backed by proportional underlying reserves"
}
```

#### 5.3 查看最关键的股份价格不变量详情
```bash
cat extracted_contracts/2024-01/BarleyFinance_exp/invariants.json | \
  jq '.storage_invariants[0]'
```

**预期输出：**
```json
{
  "id": "SINV_001",
  "type": "share_price_stability",
  "severity": "critical",
  "description": "Vault share price must not change more than 5% per transaction",
  "formula": "|(reserves/totalSupply)_after - (reserves/totalSupply)_before| / (reserves/totalSupply)_before <= 0.05",
  "contracts": [
    "0x356e7481b957be0165d6751a49b4b7194aef18d5",
    "0x04c80Bb477890F3021F03B068238836Ee20aA0b8"
  ],
  "slots": {
    "totalSupply_slot": "2",
    "totalSupply_contract": "0x356e7481b957be0165d6751a49b4b7194aef18d5",
    "reserves_contract": "0x04c80Bb477890F3021F03B068238836Ee20aA0b8",
    "reserves_query": "0x04c80Bb477890F3021F03B068238836Ee20aA0b8.balanceOf(...)"
  },
  "threshold": 0.05,
  "reason": "Vault pattern detected. Share price manipulation indicates attack.",
  "violation_impact": "Allows attacker to mint underpriced shares and drain underlying assets",
  "confidence": 0.9
}
```

#### 5.4 查看协议检测信息
```bash
cat extracted_contracts/2024-01/BarleyFinance_exp/invariants.json | \
  jq '.storage_analysis_metadata.protocol_info'
```

**预期输出：**
```json
{
  "type": "vault",
  "confidence": 0.65,
  "evidence": [
    "Contract 0x356e7481... has totalSupply at slot 2",
    "Found 4 address references in storage",
    "Found 4 other ERC20 contracts in the set"
  ],
  "primary_contract": "0x356e7481b957be0165d6751a49b4b7194aef18d5",
  "metadata": {
    "share_token": "0x356e7481b957be0165d6751a49b4b7194aef18d5",
    "underlying_token": "0x04c80Bb477890F3021F03B068238836Ee20aA0b8",
    "detection_method": "inferred_from_multiple_erc20s"
  }
}
```

---

## 📊 输出文件结构

生成的 `invariants.json` 包含以下部分：

```json
{
  "project": "BarleyFinance_exp",
  "generated_at": "2025-10-28T07:38:59",
  "generation_method": "from_monitor_output_with_storage_analysis",
  "source_file": "autopath/barleyfinance_analysis.json",
  "attack_tx": "0x995e...",

  "monitor_summary": {
    "total_violations": 6,
    "attack_detected": true
  },

  "execution_invariants": [
    {
      "id": "INV_001",
      "type": "balance_change_rate",
      "threshold": 0.435,
      "measured_value": 0.87,
      ...
    }
  ],

  "storage_invariants": [
    {
      "id": "SINV_001",
      "type": "share_price_stability",
      "formula": "|(reserves/totalSupply)_after - ...| <= 0.05",
      "severity": "critical",
      ...
    }
  ],

  "storage_analysis_metadata": {
    "protocol_info": {
      "type": "vault",
      "confidence": 0.65
    },
    "relationships_detected": 4
  }
}
```

---

## 🔍 关键不变量说明

### SINV_001: share_price_stability（股份价格稳定性）

**这是最关键的不变量！**

**公式：**
```
|(reserves/totalSupply)_after - (reserves/totalSupply)_before| / (reserves/totalSupply)_before <= 0.05
```

**含义：**
- 单次交易中，Vault 的股份价格（每股对应的底层资产数量）不应变化超过 5%

**为什么能检测 BarleyFinance 攻击：**
1. 攻击者通过重入在 20 次循环中调用 `flash()` + `bond()`
2. 每次循环都铸造新的 wBARL 股份（totalSupply 增加）
3. 但底层的 BARL 储备金没有相应增加
4. 结果：`reserves / totalSupply` 急剧下降
5. **违反了 SINV_001 不变量** → 攻击被检测！

---

## 🎯 与执行级不变量的对比

### 执行级不变量（症状）
```json
{
  "type": "loop_iterations",
  "threshold": 10,
  "measured_value": 20,
  "description": "单个交易中循环迭代次数不应超过10次"
}
```
❌ **问题：** 这只是告诉你"有异常循环"，但不知道为什么这是攻击

### 存储级不变量（根因）
```json
{
  "type": "share_price_stability",
  "formula": "|(reserves/totalSupply)_after - ...| <= 0.05",
  "description": "Vault股份价格不应变化超过5%"
}
```
✅ **优势：** 直接指出"股份价格被操纵"，这是攻击的根本原因！

---

## 🛠️ 故障排查

### 问题 1: "未找到 attack_state.json"
```bash
# 检查文件是否存在
ls extracted_contracts/2024-01/BarleyFinance_exp/attack_state.json

# 如果不存在，重新运行步骤 2
python src/test/collect_attack_states.py --filter BarleyFinance_exp
```

### 问题 2: "Anvil 连接失败"
```bash
# 检查 Anvil 是否运行
netstat -tuln | grep 8545

# 重启 Anvil
pkill anvil
anvil --fork-url YOUR_RPC_URL --fork-block-number 19106654 --port 8545
```

### 问题 3: "协议检测置信度为 0"
这可能是因为：
- attack_state.json 中缺少某些合约
- 存储槽数据不完整

**解决方法：** 检查 attack_state.json 是否包含所有相关合约

---

## 📚 下一步

### 应用到其他项目
```bash
# 通用模板
python src/test/generate_invariants_from_monitor.py \
  --monitor-output autopath/<project>_analysis.json \
  --output extracted_contracts/YYYY-MM/<ProjectName>/invariants.json \
  --project <ProjectName>
```

### 批量处理
```bash
# 处理所有 2024-01 的项目
for dir in extracted_contracts/2024-01/*/; do
  project=$(basename $dir)
  echo "Processing $project..."
  python src/test/generate_invariants_from_monitor.py \
    --monitor-output autopath/${project}_analysis.json \
    --output ${dir}/invariants.json \
    --project $project
done
```

---

## ✨ 总结

**完整流程回顾：**
1. ✅ 启动 Anvil（本地 fork 链）
2. ✅ 收集攻击状态 → `attack_state.json`
3. ✅ 运行 Monitor（可选）→ `*_analysis.json`
4. ✅ 生成不变量 → `invariants.json`（包含执行级 + 存储级）
5. ✅ 分析结果

**关键文件：**
- 输入: `attack_state.json` + `*_analysis.json`
- 输出: `invariants.json`（含 execution + storage 两部分）

**核心创新：**
- 从"症状检测"（循环次数）→ "根因检测"（股份价格操纵）
- 自动识别协议类型（Vault/AMM/Lending）
- 生成可直接用于链上监控的不变量规则
