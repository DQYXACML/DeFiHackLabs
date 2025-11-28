"""
跨合约关系分析器

识别和分析多个合约之间的关系和依赖。
"""

import logging
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ContractRelationship:
    """合约关系"""
    contract_a: str
    contract_b: str
    relation_type: str  # "owns", "delegates", "depends_on", "balance_in"
    description: str
    confidence: float = 0.0


class CrossContractAnalyzer:
    """
    跨合约关系分析器

    分析多个合约之间的关系,识别:
    - 所有权关系
    - 余额依赖
    - 价格依赖
    - 调用关系
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.CrossContractAnalyzer')

    def analyze_relationships(
        self,
        contracts: Dict[str, any],  # address -> contract_info
        diff_report: any = None
    ) -> List[ContractRelationship]:
        """
        分析合约间关系

        Args:
            contracts: 合约信息字典
            diff_report: 差异报告 (可选,用于识别动态关系)

        Returns:
            ContractRelationship列表
        """
        relationships = []

        # 从diff_report中提取跨合约关系
        if diff_report:
            for relation in diff_report.cross_contract_relations:
                relationships.append(ContractRelationship(
                    contract_a=relation.contracts[0] if len(relation.contracts) > 0 else "",
                    contract_b=relation.contracts[1] if len(relation.contracts) > 1 else "",
                    relation_type=relation.relation_type,
                    description=relation.description,
                    confidence=relation.correlation_score
                ))

        self.logger.info(f"分析到 {len(relationships)} 个跨合约关系")
        return relationships

    def find_vault_underlying_pairs(
        self,
        contracts: Dict[str, any],
        protocol_types: Dict[str, str]
    ) -> List[Tuple[str, str]]:
        """
        查找Vault及其底层资产对

        Returns:
            [(vault_address, underlying_address), ...]
        """
        pairs = []

        for address, ptype in protocol_types.items():
            if ptype == "vault":
                # 简化实现: 假设从合约状态中可以找到underlying地址
                # 实际实现需要从storage或ABI推断
                self.logger.debug(f"Found vault: {address}")
                # pairs.append((address, underlying_address))

        return pairs

    def identify_dependency_chain(
        self,
        relationships: List[ContractRelationship]
    ) -> List[List[str]]:
        """
        识别依赖链

        Returns:
            依赖链列表 [[A, B, C], ...] 表示 A依赖B, B依赖C
        """
        chains = []

        # 简化实现: 构建基础链
        for rel in relationships:
            chains.append([rel.contract_a, rel.contract_b])

        return chains
