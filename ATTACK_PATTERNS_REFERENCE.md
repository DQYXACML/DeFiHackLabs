# DeFi攻击模式参考手册

本文档详细描述了约束提取系统支持的11种DeFi攻击模式。

## 模式索引

| 模式ID | 名称 | 关键词数 | 状态 | 示例协议 |
|-------|------|---------|------|----------|
| 1 | flashloan_attack | 2 | ⏳待验证 | - |
| 2 | borrow_attack | 1 | ✅已验证 | MIMSpell2 |
| 3 | repay_manipulation | 3 | ✅已验证 | MIMSpell2 |
| 4 | large_deposit | 5 | ✅已验证 | BarleyFinance, PeapodsFinance, RadiantCapital |
| 5 | drain_attack | 5 | ✅已验证 | RadiantCapital, NBLGAME, CitadelFinance |
| 6 | collateral_manipulation | 3 | ✅已验证 | MIMSpell2 |
| 7 | swap_manipulation | 3 | ⏳待验证 | (可能: MIC) |
| 8 | price_oracle_attack | 4 | ⏳待验证 | - |
| 9 | reentrancy_attack | 4 | ⏳待验证 | - |
| 10 | governance_attack | 4 | ⏳待验证 | - |
| 11 | bridge_attack | 4 | ⏳待验证 | (可能: OrbitChain) |
| 12 | nft_manipulation | 3 | ⏳待验证 | - |

---

## 1. 闪电贷攻击 (flashloan_attack)

### 基本信息
- **描述**: 借用大额资金进行套利或操纵
- **风险等级**: 🔴 高
- **典型场景**: 价格操纵、清算攻击、治理投票

### 关键词匹配
```python
keywords = ['flashloan', 'flash']
```

### 约束模板
```javascript
amount > totalLiquidity * 0.3
```
- **危险条件**: 借款金额超过池子流动性的30%
- **安全条件**: 借款金额不超过流动性的5%

### 生成的约束结构
```json
{
  "function": "flashLoan",
  "signature": "flashLoan(address,address,address,uint256,bytes)",
  "attack_pattern": "flashloan_attack",
  "constraint": {
    "expression": "amount > totalLiquidity * 0.3",
    "semantics": "Large flashloan exceeding 30% of pool liquidity",
    "variables": {
      "amount": {
        "source": "function_parameter",
        "index": 3,
        "type": "uint256"
      },
      "totalLiquidity": {
        "source": "storage",
        "slot": "0x3",
        "type": "uint256",
        "semantic_name": "totalLiquidity"
      }
    }
  }
}
```

### 真实案例
- **协议**: (待补充)
- **损失**: -
- **攻击手法**: -

---

## 2. 过度借贷攻击 (borrow_attack) ✅

### 基本信息
- **描述**: 借走池子大部分资金导致流动性枯竭
- **风险等级**: 🔴 高
- **典型场景**: 借贷协议流动性攻击

### 关键词匹配
```python
keywords = ['borrow']
```

### 约束模板
```javascript
amount > availableLiquidity * 0.8
```
- **危险条件**: 借款金额超过可用流动性的80%
- **安全条件**: 借款金额不超过流动性的30%

### 真实案例
- **协议**: MIMSpell2_exp
- **函数**: `borrow(address,uint256)`
- **参数**: `DegenBox.balanceOf(address(MIM), address(CauldronV4))`
- **约束数**: 3个 (循环调用)
- **攻击特征**: 配合最小还款操纵会计逻辑

### 提取示例
```json
{
  "function": "borrow",
  "attack_pattern": "borrow_attack",
  "constraint": {
    "expression": "amount > availableLiquidity * 0.8",
    "semantics": "Excessive borrowing depleting pool liquidity",
    "danger_condition": "amount > availableLiquidity * 0.8",
    "safe_condition": "amount <= availableLiquidity * 0.3"
  }
}
```

---

## 3. 还款操纵攻击 (repay_manipulation) ✅

### 基本信息
- **描述**: 通过异常还款操纵债务跟踪系统
- **风险等级**: 🟡 中
- **典型场景**: 最小还款绕过检查、债务追踪漏洞

### 关键词匹配
```python
keywords = ['repay', 'repayall', 'repayforall']
```

### 约束模板
```javascript
amount > borrowedAmount * 0.9
```
- **危险条件**: 还款金额超过借款金额的90%
- **安全条件**: 还款金额不超过借款金额的50%

### 真实案例
- **协议**: MIMSpell2_exp
- **函数**: `repay(address,bool,uint256)`
- **参数**: `1` (最小还款)
- **约束数**: 3个
- **攻击特征**: 循环最小还款(1 wei)可能绕过某些会计检查

### 提取示例
```json
{
  "function": "repay",
  "attack_pattern": "repay_manipulation",
  "constraint": {
    "expression": "amount > borrowedAmount * 0.9",
    "semantics": "Large repayment potentially manipulating debt tracking",
    "variables": {
      "borrowedAmount": {
        "source": "storage",
        "slot": "dynamic",
        "semantic_name": "userBorrowPart"
      }
    }
  }
}
```

---

## 4. 大额存款攻击 (large_deposit) ✅

### 基本信息
- **描述**: 存入大额资金操纵价格或权重
- **风险等级**: 🟡 中
- **典型场景**: 份额操纵、投票权攻击、价格影响

### 关键词匹配
```python
keywords = ['deposit', 'bond', 'stake', 'mint', 'supply']
```

### 约束模板
```javascript
amount > totalSupply * 0.5
```
- **危险条件**: 存款金额超过总供应量的50%
- **安全条件**: 存款金额不超过总供应量的10%

### 真实案例
- **协议**: BarleyFinance_exp
- **函数**: `bond(address,uint256)`
- **参数**: `BARL.balanceOf(address(this))`
- **约束数**: 2个
- **攻击特征**: 循环20次bond/debond操纵份额

### 提取示例
```json
{
  "function": "bond",
  "attack_pattern": "large_deposit",
  "constraint": {
    "expression": "amount > totalSupply * 0.5",
    "semantics": "Large deposit exceeding 50% of total supply",
    "variables": {
      "totalSupply": {
        "source": "storage",
        "slot": "0x2",
        "semantic_name": "totalSupply"
      }
    }
  }
}
```

---

## 5. 资金抽取攻击 (drain_attack) ✅

### 基本信息
- **描述**: 一次性取出大部分余额
- **风险等级**: 🔴 高
- **典型场景**: 权限漏洞、会计错误

### 关键词匹配
```python
keywords = ['withdraw', 'debond', 'unstake', 'redeem', 'burn']
```

### 约束模板
```javascript
amount > balance * 0.8
```
- **危险条件**: 提款金额超过余额的80%
- **安全条件**: 提款金额不超过余额的50%

### 真实案例
- **协议**: CitadelFinance_exp
- **函数**: `redeem(uint256,address[],uint8[])`
- **参数**: `1`
- **约束数**: 1个
- **攻击特征**: 提取攻击者自己的余额

### 提取示例
```json
{
  "function": "redeem",
  "attack_pattern": "drain_attack",
  "constraint": {
    "expression": "amount > userBalance * 0.9",
    "semantics": "Draining large portion of user balance",
    "variables": {
      "userBalance": {
        "source": "storage",
        "slot": "dynamic",
        "semantic_name": "balanceOf(attacker)"
      }
    }
  }
}
```

---

## 6. 抵押品操纵攻击 (collateral_manipulation) ✅

### 基本信息
- **描述**: 操纵抵押品数量影响清算阈值
- **风险等级**: 🟡 中
- **典型场景**: 借贷协议清算机制漏洞

### 关键词匹配
```python
keywords = ['addcollateral', 'removecollateral', 'liquidate']
```

### 约束模板
```javascript
amount > userCollateral * 0.9
```
- **危险条件**: 抵押品变化超过用户抵押品的90%
- **安全条件**: 抵押品变化不超过用户抵押品的30%

### 真实案例
- **协议**: MIMSpell2_exp
- **函数**: `addCollateral(address,bool,uint256)`
- **参数**: `depositAmount - 100`
- **约束数**: 2个
- **攻击特征**: 配合borrow和repay操纵清算逻辑

### 提取示例
```json
{
  "function": "addCollateral",
  "attack_pattern": "collateral_manipulation",
  "constraint": {
    "expression": "amount > userCollateral * 0.9",
    "semantics": "Large collateral change affecting liquidation threshold",
    "variables": {
      "userCollateral": {
        "source": "storage",
        "slot": "dynamic",
        "semantic_name": "userCollateralShare"
      }
    }
  }
}
```

---

## 7. Swap价格操纵 (swap_manipulation)

### 基本信息
- **描述**: 通过大额swap操纵AMM价格
- **风险等级**: 🔴 高
- **典型场景**: 预言机价格操纵、套利攻击

### 关键词匹配
```python
keywords = ['swap', 'swapmanual', 'swapexact']
```

### 约束模板
```javascript
amountIn > reserve * 0.3
```
- **危险条件**: swap金额超过储备量的30%
- **安全条件**: swap金额不超过储备量的5%

### 潜在案例
- **协议**: MIC_exp (待验证)
- **函数**: `swapManual()`
- **状态**: 参数未被识别为dynamic,需要修复

### 提取示例
```json
{
  "function": "swapManual",
  "attack_pattern": "swap_manipulation",
  "constraint": {
    "expression": "amountIn > reserve * 0.3",
    "semantics": "Large swap causing significant price slippage",
    "variables": {
      "reserve": {
        "source": "storage",
        "slot": "0x5",
        "semantic_name": "reserve"
      }
    }
  }
}
```

---

## 8. 价格预言机攻击 (price_oracle_attack)

### 基本信息
- **描述**: 操纵交易量影响预言机价格
- **风险等级**: 🔴 高
- **典型场景**: TWAP操纵、Spot价格操纵

### 关键词匹配
```python
keywords = ['trade', 'exchange', 'buy', 'sell']
```

### 约束模板
```javascript
amount > poolBalance * 0.25
```
- **危险条件**: 交易金额超过池子余额的25%
- **安全条件**: 交易金额不超过池子余额的5%

### 提取示例
```json
{
  "function": "trade",
  "attack_pattern": "price_oracle_attack",
  "constraint": {
    "expression": "amount > poolBalance * 0.25",
    "semantics": "Trade volume manipulating oracle price",
    "variables": {
      "poolBalance": {
        "source": "storage",
        "slot": "0x6",
        "semantic_name": "poolBalance"
      }
    }
  }
}
```

---

## 9. 重入攻击 (reentrancy_attack)

### 基本信息
- **描述**: 通过回调重入函数逻辑
- **风险等级**: 🔴 高
- **典型场景**: 状态更新前的外部调用

### 关键词匹配
```python
keywords = ['callback', 'onflashloan', 'receive', 'fallback']
```

### 约束模板
```javascript
callDepth > maxDepth
```
- **危险条件**: 调用深度超过最大深度
- **安全条件**: 单次调用

### 提取示例
```json
{
  "function": "onFlashLoan",
  "attack_pattern": "reentrancy_attack",
  "constraint": {
    "expression": "callDepth > maxDepth",
    "semantics": "Reentrant call exceeding maximum depth"
  }
}
```

---

## 10. 治理攻击 (governance_attack)

### 基本信息
- **描述**: 利用投票权进行恶意治理
- **风险等级**: 🟡 中
- **典型场景**: 闪电贷投票、提案攻击

### 关键词匹配
```python
keywords = ['vote', 'propose', 'execute', 'delegate']
```

### 约束模板
```javascript
votingPower > totalVotes * 0.5
```
- **危险条件**: 投票权超过总投票权的50%
- **安全条件**: 投票权不超过总投票权的10%

### 提取示例
```json
{
  "function": "vote",
  "attack_pattern": "governance_attack",
  "constraint": {
    "expression": "votingPower > totalVotes * 0.5",
    "semantics": "Controlling majority of voting power"
  }
}
```

---

## 11. 跨链桥攻击 (bridge_attack)

### 基本信息
- **描述**: 操纵跨链资产转移
- **风险等级**: 🔴 高
- **典型场景**: 双花攻击、签名伪造

### 关键词匹配
```python
keywords = ['bridge', 'relay', 'lock', 'unlock']
```

### 约束模板
```javascript
amount > bridgeBalance * 0.7
```
- **危险条件**: 跨链金额超过桥余额的70%
- **安全条件**: 跨链金额不超过桥余额的10%

### 潜在案例
- **协议**: OrbitChain_exp (待验证)
- **函数**: (待分析)
- **状态**: 合约已识别但函数未匹配关键词

### 提取示例
```json
{
  "function": "bridge",
  "attack_pattern": "bridge_attack",
  "constraint": {
    "expression": "amount > bridgeBalance * 0.7",
    "semantics": "Large cross-chain transfer",
    "variables": {
      "bridgeBalance": {
        "source": "storage",
        "slot": "dynamic",
        "semantic_name": "lockedBalance"
      }
    }
  }
}
```

---

## 12. NFT/奖励操纵 (nft_manipulation)

### 基本信息
- **描述**: 操纵NFT质押或奖励计算
- **风险等级**: 🟡 中
- **典型场景**: 奖励通胀、质押权重操纵

### 关键词匹配
```python
keywords = ['claim', 'harvest', 'compound']
```

### 约束模板
```javascript
amount > pendingRewards * 0.8
```
- **危险条件**: 领取金额超过待领取奖励的80%
- **安全条件**: 领取金额不超过待领取奖励的50%

### 提取示例
```json
{
  "function": "claim",
  "attack_pattern": "nft_manipulation",
  "constraint": {
    "expression": "claimAmount > pendingRewards * 0.8",
    "semantics": "Claiming excessive rewards through manipulation",
    "variables": {
      "pendingRewards": {
        "source": "storage",
        "slot": "dynamic",
        "semantic_name": "userPendingRewards"
      }
    }
  }
}
```

---

## 使用指南

### 如何添加新模式

1. 在`ATTACK_PATTERNS`字典中添加新条目:
```python
'new_attack': {
    'keywords': ['keyword1', 'keyword2'],
    'description': '攻击描述',
    'constraint_template': 'param > state * threshold'
}
```

2. 在`_generate_constraint_from_pattern()`中实现约束生成逻辑:
```python
elif pattern == 'new_attack':
    return {
        "function": func_name,
        "signature": f"{func_name}(...)",
        "attack_pattern": pattern,
        "constraint": {...}
    }
```

3. 在2024-01目录的协议上测试验证:
```bash
python3 DeFiHackLabs/extract_param_state_constraints.py --batch --filter 2024-01
```

### 如何扩展关键词

直接编辑`ATTACK_PATTERNS`中的`keywords`列表:
```python
'bridge_attack': {
    'keywords': ['bridge', 'relay', 'lock', 'unlock', 
                 'depositETH', 'withdrawETH'],  # 新增
    ...
}
```

### 如何调整阈值

修改`_generate_constraint_from_pattern()`中的阈值系数:
```python
# 从0.8改为0.9
"danger_condition": "amount > availableLiquidity * 0.9",
```

---

## 附录: 统计数据

### 模式覆盖率 (基于2024-01测试)
- **已验证模式**: 5/11 (45.5%)
- **生效协议数**: 6/19 (31.6%)
- **生成约束数**: 26

### 高频攻击类型 (按约束数排序)
1. `borrow_attack`: 3个约束 (MIMSpell2)
2. `repay_manipulation`: 3个约束 (MIMSpell2)
3. `large_deposit`: 9个约束 (多个协议)
4. `drain_attack`: 7个约束 (多个协议)
5. `collateral_manipulation`: 2个约束 (MIMSpell2)

### 待改进模式
- `flashloan_attack`: 需要真实测试数据
- `swap_manipulation`: MIC_exp参数识别问题
- `bridge_attack`: OrbitChain关键词不匹配
- `reentrancy_attack`: 无测试数据
- `governance_attack`: 无测试数据
- `nft_manipulation`: 无测试数据

---

**最后更新**: 2025-11-21  
**版本**: V2  
**维护者**: FirewallOnchain Team
