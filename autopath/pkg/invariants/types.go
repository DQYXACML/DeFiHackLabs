package invariants

import (
	"autopath/pkg/types"
)

// InvariantRule 不变量规则定义
type InvariantRule struct {
	ID          string                 `json:"id"`
	Type        string                 `json:"type"`
	Severity    string                 `json:"severity"`
	Description string                 `json:"description"`
	Contract    string                 `json:"contract,omitempty"`
	Function    string                 `json:"function,omitempty"`
	Threshold   interface{}            `json:"threshold"`
	Confidence  float64                `json:"confidence"`
	Metadata    map[string]interface{} `json:"metadata"`
}

// Invariants 不变量集合接口
type Invariants interface {
	// GetProtocol 获取协议名称
	GetProtocol() string

	// GetChain 获取链名称
	GetChain() string

	// GetContracts 获取相关合约地址
	GetContracts() map[string]string

	// GetRules 获取所有不变量规则
	GetRules() []InvariantRule

	// Evaluate 评估交易数据，返回违规详情
	Evaluate(txData *types.TransactionData) []types.ViolationDetail
}
