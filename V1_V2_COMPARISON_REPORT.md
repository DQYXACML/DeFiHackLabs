# InvariantGenerator V1 vs V2 对比报告

生成时间: generate_v1_v2_comparison

## 执行摘要

- **总协议数**: 18
- **v1不变量总数**: 291
- **v2不变量总数**: 48
- **整体改进**: -83.5%

## 协议类型检测能力

| 协议类型 | 检测数量 |
|---------|---------|
| unknown | 6 |
| erc20 | 3 |
| lending | 2 |
| amm | 2 |
| bridge | 1 |
| governance | 1 |

平均检测置信度: **60.00%**

## 质量分析

- 平均质量得分: **47.89/100**
- 最高得分: 81.08
- 最低得分: 0.18

### 得分分布

- excellent (80-100): 1 个协议
- good (60-80): 4 个协议
- fair (40-60): 6 个协议
- poor (<40): 4 个协议

## 详细协议对比

| 协议名称 | 类型 | v1不变量 | v2不变量 | 攻击模式 | 质量得分 |
|---------|------|---------|---------|---------|---------|
| WiseLending02_exp | lending | 22 | 8 | 65 | 81.08 |
| Gamma_exp | amm | 17 | 7 | 16 | 78.92 |
| WiseLending03_exp | lending | 31 | 6 | 40 | 75.11 |
| DAO_SoulMate_exp | governance | 12 | 4 | 59 | 68.74 |
| Shell_MEV_0xa898_exp | erc20 | 8 | 3 | 12 | 64.11 |
| BarleyFinance_exp | amm | 7 | 2 | 6 | 56.81 |
| RadiantCapital_exp | unknown | 53 | 7 | 21 | 56.75 |
| PeapodsFinance_exp | erc20 | 7 | 2 | 10 | 55.96 |
| SocketGateway_exp | bridge | 4 | 1 | 2 | 52.48 |
| NBLGAME_exp | unknown | 9 | 5 | 16 | 49.84 |
| Bmizapper_exp | erc20 | 17 | 1 | 2 | 42.55 |
| Freedom_exp | unknown | 15 | 2 | 9 | 35.39 |
| MIMSpell2_exp | unknown | 21 | 0 | 0 | 0.23 |
| XSIJ_exp | unknown | 22 | 0 | 0 | 0.20 |
| MIC_exp | unknown | 11 | 0 | 0 | 0.18 |
| OrbitChain_exp | None | 8 | 0 | 0 | 0.00 |
| CitadelFinance_exp | None | 17 | 0 | 0 | 0.00 |
| LQDX_alert_exp | None | 10 | 0 | 0 | 0.00 |


## V2版本改进亮点

1. **协议类型自动检测**: 基于多源融合算法,平均置信度达到 60.00%
2. **攻击模式识别**: 自动检测10+种攻击模式(闪电贷、价格操纵、重入等)
3. **语义槽位映射**: 自动识别32种存储槽位语义(totalSupply, balance等)
4. **状态变化分析**: 量化分析合约状态变化幅度(7级变化等级)
5. **模板驱动生成**: 针对不同协议类型使用18+种业务逻辑模板
