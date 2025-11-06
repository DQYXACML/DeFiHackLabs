package analyzer

import (
	"autopath/pkg/types"
	"context"
	"fmt"
	"math/big"
	"strings"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/ethclient"
)

// DataExtractor 数据提取器
type DataExtractor struct {
	client *ethclient.Client
}

// NewDataExtractor 创建数据提取器
func NewDataExtractor(client *ethclient.Client) *DataExtractor {
	return &DataExtractor{
		client: client,
	}
}

// ExtractBalanceChanges 提取余额变化
func (de *DataExtractor) ExtractBalanceChanges(
	ctx context.Context,
	txData *types.TransactionData,
	addresses []string,
) error {
	blockNum := new(big.Int).SetUint64(txData.BlockNumber)

	for _, addr := range addresses {
		address := common.HexToAddress(addr)

		// 获取交易前余额（前一个区块）
		beforeBlock := new(big.Int).Sub(blockNum, big.NewInt(1))
		balanceBefore, err := de.client.BalanceAt(ctx, address, beforeBlock)
		if err != nil {
			return fmt.Errorf("获取地址 %s 交易前余额失败: %w", addr, err)
		}

		// 获取交易后余额（当前区块）
		balanceAfter, err := de.client.BalanceAt(ctx, address, blockNum)
		if err != nil {
			return fmt.Errorf("获取地址 %s 交易后余额失败: %w", addr, err)
		}

		// 计算变化
		difference := new(big.Int).Sub(balanceAfter, balanceBefore)

		// 计算变化率（百分比）
		changeRate := 0.0
		if balanceBefore.Cmp(big.NewInt(0)) > 0 {
			// changeRate = (difference / before) * 100
			changeRateBig := new(big.Float).Quo(
				new(big.Float).SetInt(difference),
				new(big.Float).SetInt(balanceBefore),
			)
			changeRateBig.Mul(changeRateBig, big.NewFloat(100))
			changeRate, _ = changeRateBig.Float64()
		} else if balanceAfter.Cmp(big.NewInt(0)) > 0 {
			// 如果before是0，after大于0，变化率是无穷大，设为一个很大的值
			changeRate = 999999.0
		}

		// 存储余额变化
		txData.BalanceChanges[strings.ToLower(addr)] = &types.BalanceChange{
			Address:    addr,
			Before:     balanceBefore,
			After:      balanceAfter,
			Difference: difference,
			ChangeRate: changeRate,
		}
	}

	return nil
}

// ExtractPoolUtilization 提取池子利用率
func (de *DataExtractor) ExtractPoolUtilization(
	ctx context.Context,
	txData *types.TransactionData,
	poolAddress string,
	borrowedAmount *big.Int,
) error {
	if poolAddress == "" || borrowedAmount == nil {
		return nil
	}

	// 获取池子在交易前的余额
	blockNum := new(big.Int).SetUint64(txData.BlockNumber)
	beforeBlock := new(big.Int).Sub(blockNum, big.NewInt(1))

	address := common.HexToAddress(poolAddress)
	poolBalance, err := de.client.BalanceAt(ctx, address, beforeBlock)
	if err != nil {
		return fmt.Errorf("获取池子余额失败: %w", err)
	}

	// 计算利用率：borrowed / pool_balance * 100
	if poolBalance.Cmp(big.NewInt(0)) > 0 {
		utilization := new(big.Float).Quo(
			new(big.Float).SetInt(borrowedAmount),
			new(big.Float).SetInt(poolBalance),
		)
		utilization.Mul(utilization, big.NewFloat(100))
		txData.PoolUtilization, _ = utilization.Float64()
		txData.PoolAddress = poolAddress
	}

	return nil
}

// ExtractFlashLoanAmount 从trace中提取闪电贷金额
func (de *DataExtractor) ExtractFlashLoanAmount(txData *types.TransactionData, flashFunctionSig string) *big.Int {
	// 查找flash函数调用
	for _, frame := range txData.CallStack {
		if strings.Contains(frame.Function, flashFunctionSig) {
			// 解析input中的amount参数
			// flash(address _recipient, address _token, uint256 _amount, bytes memory _data)
			// 函数选择器4字节 + address 32字节 + address 32字节 + uint256 32字节
			if len(frame.Input) >= 138 { // 4+32+32+32 字节的十六进制表示
				amountHex := "0x" + frame.Input[74:138]
				if amount, ok := new(big.Int).SetString(amountHex, 0); ok {
					return amount
				}
			}
		}
	}

	return big.NewInt(0)
}

// AnalyzeCallPattern 分析调用模式
func (de *DataExtractor) AnalyzeCallPattern(txData *types.TransactionData, patterns []string) map[string]int {
	patternCounts := make(map[string]int)

	for _, pattern := range patterns {
		count := 0
		for _, funcCall := range txData.CallSequence {
			if strings.Contains(strings.ToLower(funcCall), strings.ToLower(pattern)) {
				count++
			}
		}
		patternCounts[pattern] = count
	}

	return patternCounts
}

// EnrichTransactionData 丰富交易数据（添加额外的分析）
func (de *DataExtractor) EnrichTransactionData(
	ctx context.Context,
	txData *types.TransactionData,
	monitoredAddresses []string,
	poolAddress string,
) error {
	// 1. 提取余额变化
	if err := de.ExtractBalanceChanges(ctx, txData, monitoredAddresses); err != nil {
		return fmt.Errorf("提取余额变化失败: %w", err)
	}

	// 2. 提取闪电贷金额并计算池子利用率
	flashAmount := de.ExtractFlashLoanAmount(txData, "0x3b30ba59") // flash函数的签名
	if flashAmount.Cmp(big.NewInt(0)) > 0 && poolAddress != "" {
		if err := de.ExtractPoolUtilization(ctx, txData, poolAddress, flashAmount); err != nil {
			return fmt.Errorf("提取池子利用率失败: %w", err)
		}
	}

	// 3. 分析调用模式
	patterns := []string{"flash", "callback", "bond", "deposit", "borrow"}
	de.AnalyzeCallPattern(txData, patterns)

	return nil
}
