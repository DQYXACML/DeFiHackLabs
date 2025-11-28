"""
因果关系图构建器 (占位实现)

分析状态变化之间的因果关系,构建变化传播路径。

注意: 这是Week 2的占位实现,完整功能需要NetworkX库。
当前版本返回简化结果,不影响核心分析流程。
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CausalityNode:
    """因果关系节点"""
    contract: str
    slot: str
    change_type: str  # "increase", "decrease", "set"


@dataclass
class CausalityEdge:
    """因果关系边"""
    source: CausalityNode
    target: CausalityNode
    weight: float  # 因果强度


class CausalityGraphBuilder:
    """
    因果关系图构建器 (占位实现)

    TODO (Week 3):
    - 集成NetworkX构建完整的有向图
    - 实现时序分析识别因果关系
    - 使用图算法找出关键路径
    - 可视化因果关系图

    当前策略:
    - 返回简化的节点和边列表
    - 提供基础的因果推断
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.CausalityGraphBuilder')
        self.logger.warning(
            "CausalityGraphBuilder当前为占位实现,完整功能将在Week 3实现。"
        )

    def build_graph(
        self,
        diff_report,  # DiffReport
        patterns: List  # List[ChangePattern]
    ) -> Dict:
        """
        构建因果关系图 (占位实现)

        Args:
            diff_report: 状态差异报告
            patterns: 检测到的模式列表

        Returns:
            简化的图结构 {nodes: [...], edges: [...]}
        """
        self.logger.debug("构建因果关系图 (简化版)...")

        nodes = []
        edges = []

        # 简化实现: 基于跨合约关系构建节点
        for relation in diff_report.cross_contract_relations:
            for i, contract in enumerate(relation.contracts):
                slot = relation.slots[i] if i < len(relation.slots) else "unknown"
                nodes.append({
                    "contract": contract,
                    "slot": slot,
                    "type": relation.relation_type
                })

            # 如果有多个合约,添加边
            if len(relation.contracts) >= 2:
                edges.append({
                    "source": relation.contracts[0],
                    "target": relation.contracts[1],
                    "weight": relation.correlation_score,
                    "type": relation.relation_type
                })

        self.logger.info(f"因果图构建完成: {len(nodes)} 个节点, {len(edges)} 条边")

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "implementation": "placeholder"
            }
        }

    def find_critical_path(self, graph: Dict) -> List:
        """
        查找关键路径 (占位实现)

        Returns:
            关键路径节点列表
        """
        self.logger.debug("查找关键路径 (占位)...")

        # 占位: 返回所有节点
        return graph.get("nodes", [])
