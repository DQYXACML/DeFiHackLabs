package types

import (
	"math/big"
	"time"
)

// TransactionData 包含交易的完整运行时数据
type TransactionData struct {
	// 基础信息
	TxHash      string    `json:"tx_hash"`
	From        string    `json:"from"`
	To          string    `json:"to"`
	BlockNumber uint64    `json:"block_number"`
	Timestamp   time.Time `json:"timestamp"`
	GasUsed     uint64    `json:"gas_used"`
	Status      uint64    `json:"status"` // 1=success, 0=failure

	// 余额变化
	BalanceChanges map[string]*BalanceChange `json:"balance_changes"`

	// 调用信息
	CallStack     []CallFrame        `json:"call_stack"`
	CallDepth     int                `json:"call_depth"`
	FunctionCalls map[string]int     `json:"function_calls"` // 函数签名 -> 调用次数
	CallSequence  []string           `json:"call_sequence"`  // 调用顺序序列

	// 循环和重入
	LoopIterations  int `json:"loop_iterations"`
	ReentrancyDepth int `json:"reentrancy_depth"`

	// Pool数据
	PoolUtilization float64 `json:"pool_utilization"`
	PoolAddress     string  `json:"pool_address,omitempty"`

	// Trace原始数据
	RawTrace interface{} `json:"raw_trace,omitempty"`
}

// BalanceChange 余额变化信息
type BalanceChange struct {
	Address    string   `json:"address"`
	Before     *big.Int `json:"before"`
	After      *big.Int `json:"after"`
	Difference *big.Int `json:"difference"` // after - before
	ChangeRate float64  `json:"change_rate"` // 变化率百分比
}

// CallFrame 调用帧信息
type CallFrame struct {
	Type     string `json:"type"`     // CALL, DELEGATECALL, STATICCALL, CREATE
	From     string `json:"from"`
	To       string `json:"to"`
	Input    string `json:"input"`
	Output   string `json:"output"`
	Value    string `json:"value"`
	Gas      uint64 `json:"gas"`
	GasUsed  uint64 `json:"gas_used"`
	Depth    int    `json:"depth"`
	Function string `json:"function"` // 函数选择器或名称
}

// ViolationDetail 不变量违规详情
type ViolationDetail struct {
	InvariantID   string                 `json:"invariant_id"`
	InvariantType string                 `json:"invariant_type"`
	Severity      string                 `json:"severity"`
	Message       string                 `json:"message"`
	Violated      bool                   `json:"violated"`
	Details       map[string]interface{} `json:"details"`
	Timestamp     time.Time              `json:"timestamp"`
}

// VerificationReport 验证报告
type VerificationReport struct {
	EventName        string            `json:"event_name"`
	Protocol         string            `json:"protocol"`
	Chain            string            `json:"chain"`
	StartTime        time.Time         `json:"start_time"`
	EndTime          time.Time         `json:"end_time"`
	TotalTxMonitored int               `json:"total_tx_monitored"`
	Violations       []ViolationDetail `json:"violations"`
	Summary          ReportSummary     `json:"summary"`

	// 运行时数据（新增）
	TransactionData *TransactionData `json:"transaction_data,omitempty"`
}

// ReportSummary 报告摘要
type ReportSummary struct {
	TotalInvariants      int     `json:"total_invariants"`
	ViolatedInvariants   int     `json:"violated_invariants"`
	TotalViolations      int     `json:"total_violations"`
	CriticalViolations   int     `json:"critical_violations"`
	HighViolations       int     `json:"high_violations"`
	MediumViolations     int     `json:"medium_violations"`
	ViolationRate        float64 `json:"violation_rate"` // 违规率
	AttackDetected       bool    `json:"attack_detected"`
	DetectionAccuracy    float64 `json:"detection_accuracy"`
}
