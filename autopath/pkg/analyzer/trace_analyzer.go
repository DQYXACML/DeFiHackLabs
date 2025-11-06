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

// TraceAnalyzer 交易trace分析器
type TraceAnalyzer struct {
	client *ethclient.Client
}

// NewTraceAnalyzer 创建trace分析器
func NewTraceAnalyzer(client *ethclient.Client) *TraceAnalyzer {
	return &TraceAnalyzer{
		client: client,
	}
}

// CallTrace 调用trace结构（与geth debug_traceTransaction返回格式对应）
type CallTrace struct {
	Type         string       `json:"type"`
	From         string       `json:"from"`
	To           string       `json:"to"`
	Value        string       `json:"value"`
	Gas          string       `json:"gas"`
	GasUsed      string       `json:"gasUsed"`
	Input        string       `json:"input"`
	Output       string       `json:"output"`
	Error        string       `json:"error,omitempty"`
	Calls        []CallTrace  `json:"calls,omitempty"`
	StructLogs   []StructLog  `json:"structLogs,omitempty"`
}

// StructLog EVM执行日志
type StructLog struct {
	Pc      uint64              `json:"pc"`
	Op      string              `json:"op"`
	Gas     uint64              `json:"gas"`
	GasCost uint64              `json:"gasCost"`
	Depth   int                 `json:"depth"`
	Stack   []string            `json:"stack,omitempty"`
	Memory  []string            `json:"memory,omitempty"`
	Storage map[string]string   `json:"storage,omitempty"`
}

// AnalyzeTransaction 分析交易trace
func (ta *TraceAnalyzer) AnalyzeTransaction(ctx context.Context, txHash string) (*types.TransactionData, error) {
	// 获取交易基本信息
	tx, isPending, err := ta.client.TransactionByHash(ctx, common.HexToHash(txHash))
	if err != nil {
		return nil, fmt.Errorf("获取交易失败: %w", err)
	}
	if isPending {
		return nil, fmt.Errorf("交易还在pending状态")
	}

	// 获取交易receipt
	receipt, err := ta.client.TransactionReceipt(ctx, common.HexToHash(txHash))
	if err != nil {
		return nil, fmt.Errorf("获取receipt失败: %w", err)
	}

	// 获取trace
	trace, err := ta.getTrace(ctx, txHash)
	if err != nil {
		return nil, fmt.Errorf("获取trace失败: %w", err)
	}

	// 构建TransactionData
	txData := &types.TransactionData{
		TxHash:         txHash,
		From:           tx.To().Hex(),
		To:             receipt.ContractAddress.Hex(),
		BlockNumber:    receipt.BlockNumber.Uint64(),
		GasUsed:        receipt.GasUsed,
		Status:         receipt.Status,
		BalanceChanges: make(map[string]*types.BalanceChange),
		FunctionCalls:  make(map[string]int),
		CallSequence:   []string{},
		RawTrace:       trace,
	}

	// 分析trace
	ta.analyzeCallTrace(trace, txData)

	return txData, nil
}

// getTrace 获取交易trace
func (ta *TraceAnalyzer) getTrace(ctx context.Context, txHash string) (*CallTrace, error) {
	var result CallTrace

	// 调用debug_traceTransaction RPC方法
	err := ta.client.Client().CallContext(ctx, &result, "debug_traceTransaction", txHash, map[string]interface{}{
		"tracer": "callTracer",
	})

	if err != nil {
		return nil, err
	}

	return &result, nil
}

// analyzeCallTrace 分析调用trace
func (ta *TraceAnalyzer) analyzeCallTrace(trace *CallTrace, txData *types.TransactionData) {
	if trace == nil {
		return
	}

	// 提取调用栈
	ta.extractCallStack(trace, txData, 0)

	// 分析循环迭代
	txData.LoopIterations = ta.detectLoopIterations(trace)

	// 分析重入深度
	txData.ReentrancyDepth = ta.calculateReentrancyDepth(trace)

	// 计算调用深度
	txData.CallDepth = ta.calculateCallDepth(trace)
}

// extractCallStack 提取调用栈和函数调用统计
func (ta *TraceAnalyzer) extractCallStack(trace *CallTrace, txData *types.TransactionData, depth int) {
	if trace == nil {
		return
	}

	// 创建调用帧
	frame := types.CallFrame{
		Type:    trace.Type,
		From:    trace.From,
		To:      trace.To,
		Input:   trace.Input,
		Output:  trace.Output,
		Value:   trace.Value,
		Depth:   depth,
	}

	// 解析gas
	if gasUsed, ok := new(big.Int).SetString(strings.TrimPrefix(trace.GasUsed, "0x"), 16); ok {
		frame.GasUsed = gasUsed.Uint64()
	}

	// 提取函数选择器（前4字节）
	if len(trace.Input) >= 10 {
		funcSig := trace.Input[:10]
		frame.Function = funcSig

		// 统计函数调用次数
		txData.FunctionCalls[funcSig]++

		// 添加到调用序列
		txData.CallSequence = append(txData.CallSequence, funcSig)
	}

	// 添加到调用栈
	txData.CallStack = append(txData.CallStack, frame)

	// 递归处理子调用
	for _, call := range trace.Calls {
		ta.extractCallStack(&call, txData, depth+1)
	}
}

// detectLoopIterations 检测循环迭代次数
func (ta *TraceAnalyzer) detectLoopIterations(trace *CallTrace) int {
	if trace == nil || len(trace.StructLogs) == 0 {
		// 如果没有structLogs，使用函数调用次数作为近似
		// 对于BarleyFinance，flash函数被调用20次
		return ta.estimateLoopFromCalls(trace)
	}

	// 通过检测JUMPI指令的重复执行来识别循环
	jumpCount := make(map[uint64]int)
	maxJumps := 0

	for _, log := range trace.StructLogs {
		if log.Op == "JUMPI" {
			jumpCount[log.Pc]++
			if jumpCount[log.Pc] > maxJumps {
				maxJumps = jumpCount[log.Pc]
			}
		}
	}

	return maxJumps
}

// estimateLoopFromCalls 从调用次数估算循环
func (ta *TraceAnalyzer) estimateLoopFromCalls(trace *CallTrace) int {
	// 统计特定函数的调用次数
	callCounts := make(map[string]int)

	ta.countCalls(trace, callCounts)

	// 找到最大调用次数（可能是循环）
	maxCount := 0
	for _, count := range callCounts {
		if count > maxCount {
			maxCount = count
		}
	}

	// 如果有函数被调用多次，可能是循环
	if maxCount > 1 {
		return maxCount
	}

	return 0
}

// countCalls 递归统计调用次数
func (ta *TraceAnalyzer) countCalls(trace *CallTrace, callCounts map[string]int) {
	if trace == nil {
		return
	}

	// 提取函数签名
	if len(trace.Input) >= 10 {
		funcSig := trace.Input[:10]
		callCounts[funcSig]++
	}

	// 递归处理子调用
	for _, call := range trace.Calls {
		ta.countCalls(&call, callCounts)
	}
}

// calculateReentrancyDepth 计算重入深度
func (ta *TraceAnalyzer) calculateReentrancyDepth(trace *CallTrace) int {
	return ta.findMaxReentrantDepth(trace, make(map[string]int), 0)
}

// findMaxReentrantDepth 查找最大重入深度
func (ta *TraceAnalyzer) findMaxReentrantDepth(trace *CallTrace, visited map[string]int, currentDepth int) int {
	if trace == nil {
		return currentDepth
	}

	address := strings.ToLower(trace.To)

	// 如果之前访问过这个地址，说明发生了重入
	if prevDepth, found := visited[address]; found {
		currentDepth = prevDepth + 1
	}

	visited[address] = currentDepth
	maxDepth := currentDepth

	// 递归检查子调用
	for _, call := range trace.Calls {
		// 创建visited的副本，避免影响兄弟调用
		visitedCopy := make(map[string]int)
		for k, v := range visited {
			visitedCopy[k] = v
		}

		depth := ta.findMaxReentrantDepth(&call, visitedCopy, currentDepth)
		if depth > maxDepth {
			maxDepth = depth
		}
	}

	return maxDepth
}

// calculateCallDepth 计算调用深度
func (ta *TraceAnalyzer) calculateCallDepth(trace *CallTrace) int {
	if trace == nil {
		return 0
	}

	maxDepth := 0
	for _, call := range trace.Calls {
		depth := 1 + ta.calculateCallDepth(&call)
		if depth > maxDepth {
			maxDepth = depth
		}
	}

	return maxDepth
}

// ExtractFunctionCallCount 提取特定函数的调用次数
func (ta *TraceAnalyzer) ExtractFunctionCallCount(txData *types.TransactionData, functionSig string) int {
	count := 0
	for sig, c := range txData.FunctionCalls {
		if strings.Contains(sig, functionSig) {
			count += c
		}
	}
	return count
}
