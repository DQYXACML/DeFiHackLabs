"""
协议检测器V2

融合多种信息源进行综合协议检测:
- ABI函数签名分析 (权重0.4)
- 事件类型分析 (权重0.3)
- 存储布局分析 (权重0.2)
- 项目名称匹配 (权重0.1)
"""

import logging
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from .abi_analyzer import ABIFunctionAnalyzer, ProtocolType
from .event_classifier import EventClassifier

logger = logging.getLogger(__name__)


@dataclass
class ProtocolResult:
    """协议检测结果"""
    detected_type: ProtocolType
    confidence: float
    protocol_scores: Dict[str, float]
    evidence: List[str]
    data_sources_used: List[str]
    details: Dict


class ProtocolDetectorV2:
    """
    协议检测器V2

    综合利用多种信息源进行协议类型检测,
    提供更准确的识别结果和置信度评分。
    """

    # 信息源权重配置
    SOURCE_WEIGHTS = {
        "abi_functions": 0.4,
        "events": 0.3,
        "storage_layout": 0.2,
        "project_name": 0.1
    }

    # 项目名称关键词模式
    NAME_PATTERNS = {
        ProtocolType.VAULT: [
            r'vault', r'yield', r'strategy', r'4626', r'erc4626',
            r'wrapper', r'yVault', r'xVault'
        ],
        ProtocolType.AMM: [
            r'swap', r'uniswap', r'pancake', r'sushi', r'dex',
            r'amm', r'pair', r'pool', r'liquidity'
        ],
        ProtocolType.LENDING: [
            r'lend', r'borrow', r'compound', r'aave', r'market',
            r'credit', r'debt', r'collateral'
        ],
        ProtocolType.STAKING: [
            r'stak', r'farm', r'reward', r'mining', r'gauge',
            r'masterchef', r'chef'
        ],
        ProtocolType.BRIDGE: [
            r'bridge', r'relay', r'cross', r'portal', r'gateway',
            r'teleport', r'wormhole'
        ],
        ProtocolType.NFT_MARKETPLACE: [
            r'nft', r'marketplace', r'opensea', r'721', r'erc721',
            r'collectible', r'auction'
        ],
        ProtocolType.GOVERNANCE: [
            r'govern', r'dao', r'vote', r'proposal', r'timelock',
            r'governor'
        ],
        ProtocolType.ERC20: [
            r'token', r'erc20', r'coin'
        ]
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.ProtocolDetectorV2')
        self.abi_analyzer = ABIFunctionAnalyzer()
        self.event_classifier = EventClassifier()

    def detect_with_confidence(
        self,
        contract_dir: Optional[Path] = None,
        abi: Optional[List[Dict]] = None,
        storage_layout: Optional[Dict] = None,
        project_name: Optional[str] = None
    ) -> ProtocolResult:
        """
        综合检测协议类型

        Args:
            contract_dir: 合约目录路径 (可从中读取abi.json等)
            abi: 合约ABI (如果提供则直接使用)
            storage_layout: 存储布局信息 (可选)
            project_name: 项目名称 (可选)

        Returns:
            ProtocolResult对象,包含检测结果和证据
        """
        self.logger.info("开始多源协议检测...")

        # 数据收集阶段
        if contract_dir:
            contract_dir = Path(contract_dir)
            abi = abi or self._load_abi(contract_dir)
            project_name = project_name or contract_dir.name

        # 各信息源的检测结果
        source_results = {}
        data_sources_used = []
        evidence = []

        # 1. ABI函数分析 (权重0.4)
        if abi:
            abi_result = self.abi_analyzer.analyze_abi(abi)
            source_results["abi_functions"] = abi_result["protocol_scores"]
            data_sources_used.append("abi_functions")
            evidence.append(f"ABI函数分析: {abi_result['detected_type'].value} (conf={abi_result['confidence']:.2f})")
            self.logger.debug(f"ABI分析完成: {abi_result['detected_type'].value}")

        # 2. 事件分析 (权重0.3)
        if abi:
            event_result = self.event_classifier.classify_by_events(abi)
            source_results["events"] = event_result["protocol_scores"]
            data_sources_used.append("events")
            evidence.append(f"事件分析: {event_result['detected_type'].value} (conf={event_result['confidence']:.2f})")
            self.logger.debug(f"事件分析完成: {event_result['detected_type'].value}")

        # 3. 存储布局分析 (权重0.2)
        if storage_layout:
            layout_result = self._analyze_storage_layout(storage_layout)
            source_results["storage_layout"] = layout_result
            data_sources_used.append("storage_layout")
            evidence.append(f"存储布局分析: 检测到 {len(storage_layout)} 个槽位")
            self.logger.debug("存储布局分析完成")

        # 4. 项目名称匹配 (权重0.1)
        if project_name:
            name_result = self._analyze_project_name(project_name)
            source_results["project_name"] = name_result
            data_sources_used.append("project_name")
            top_name_match = max(name_result.items(), key=lambda x: x[1])
            if top_name_match[1] > 0:
                evidence.append(f"项目名称匹配: {top_name_match[0]} (score={top_name_match[1]:.2f})")
            self.logger.debug("项目名称分析完成")

        # 加权融合各信息源的结果
        final_scores = self._merge_scores(source_results)

        # 确定最佳匹配
        best_protocol = max(final_scores.items(), key=lambda x: x[1])
        detected_type = ProtocolType(best_protocol[0]) if best_protocol[1] > 0 else ProtocolType.UNKNOWN
        confidence = best_protocol[1]

        self.logger.info(f"最终检测结果: {detected_type.value} (置信度: {confidence:.2%})")

        return ProtocolResult(
            detected_type=detected_type,
            confidence=confidence,
            protocol_scores=final_scores,
            evidence=evidence,
            data_sources_used=data_sources_used,
            details={
                "source_results": source_results,
                "weights_used": {k: v for k, v in self.SOURCE_WEIGHTS.items() if k in data_sources_used}
            }
        )

    def _load_abi(self, contract_dir: Path) -> Optional[List[Dict]]:
        """从目录加载ABI文件"""
        abi_path = contract_dir / "abi.json"
        if not abi_path.exists():
            self.logger.warning(f"ABI文件不存在: {abi_path}")
            return None

        try:
            with open(abi_path, 'r', encoding='utf-8') as f:
                abi = json.load(f)
            self.logger.debug(f"成功加载ABI: {abi_path}")
            return abi
        except Exception as e:
            self.logger.error(f"加载ABI失败: {e}")
            return None

    def _analyze_storage_layout(self, storage_layout: Dict) -> Dict[str, float]:
        """
        分析存储布局推断协议类型

        通过识别关键槽位的语义类型来推断协议。
        例如:
        - RESERVE槽位多 → 可能是AMM或Vault
        - DEBT/COLLATERAL槽位 → 可能是Lending
        - REWARD相关槽位 → 可能是Staking
        """
        protocol_scores = {pt.value: 0.0 for pt in ProtocolType}

        # 从存储布局中提取语义类型信息
        # 这里假设storage_layout是 {slot: SlotInfo} 或包含语义信息的字典
        semantic_types = []

        for slot, info in storage_layout.items():
            # 如果info包含semantic_type字段
            if isinstance(info, dict) and "semantic_type" in info:
                semantic_types.append(info["semantic_type"])

        # 基于语义类型的简单计数评分
        type_counter = {}
        for st in semantic_types:
            type_counter[st] = type_counter.get(st, 0) + 1

        # 协议特征模式识别
        # Vault: 通常有totalSupply, totalAssets, underlying
        if "TOTAL_SUPPLY" in type_counter and "RESERVE" in type_counter:
            protocol_scores[ProtocolType.VAULT.value] = 0.6

        # AMM: 通常有reserve0, reserve1
        if type_counter.get("RESERVE", 0) >= 2:
            protocol_scores[ProtocolType.AMM.value] = 0.7

        # Lending: 通常有borrowBalance, collateral, debt
        if "DEBT" in type_counter or "COLLATERAL" in type_counter:
            protocol_scores[ProtocolType.LENDING.value] = 0.7

        # Staking: 通常有rewardPerToken, earned
        if "REWARD" in type_counter or "REWARD_PER_TOKEN" in type_counter:
            protocol_scores[ProtocolType.STAKING.value] = 0.6

        return protocol_scores

    def _analyze_project_name(self, project_name: str) -> Dict[str, float]:
        """基于项目名称匹配协议类型"""
        protocol_scores = {pt.value: 0.0 for pt in ProtocolType}

        # 转换为小写便于匹配
        name_lower = project_name.lower()

        # 遍历所有协议类型的名称模式
        for protocol_type, patterns in self.NAME_PATTERNS.items():
            match_count = 0
            for pattern in patterns:
                if re.search(pattern, name_lower):
                    match_count += 1

            # 匹配的模式越多,分数越高
            if match_count > 0:
                protocol_scores[protocol_type.value] = min(match_count * 0.3, 1.0)

        return protocol_scores

    def _merge_scores(self, source_results: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """
        加权融合各信息源的评分

        使用SOURCE_WEIGHTS定义的权重进行加权平均。
        """
        # 初始化最终分数
        final_scores = {pt.value: 0.0 for pt in ProtocolType}

        # 计算总权重 (仅包含实际使用的信息源)
        total_weight = sum(
            self.SOURCE_WEIGHTS.get(source, 0)
            for source in source_results.keys()
        )

        if total_weight == 0:
            self.logger.warning("没有可用的信息源进行评分")
            return final_scores

        # 加权求和
        for source, scores in source_results.items():
            weight = self.SOURCE_WEIGHTS.get(source, 0) / total_weight

            for protocol_type, score in scores.items():
                final_scores[protocol_type] += score * weight

        # 标准化到[0, 1]
        max_score = max(final_scores.values()) if final_scores.values() else 1.0
        if max_score > 0:
            final_scores = {k: v / max_score for k, v in final_scores.items()}

        return final_scores

    def batch_detect(self, contract_dirs: List[Path]) -> Dict[str, ProtocolResult]:
        """批量检测多个合约的协议类型"""
        results = {}

        self.logger.info(f"开始批量检测 {len(contract_dirs)} 个合约...")

        for contract_dir in contract_dirs:
            try:
                result = self.detect_with_confidence(contract_dir=contract_dir)
                results[contract_dir.name] = result
                self.logger.info(
                    f"  {contract_dir.name}: {result.detected_type.value} "
                    f"(confidence={result.confidence:.2%})"
                )
            except Exception as e:
                self.logger.error(f"检测 {contract_dir.name} 时出错: {e}")
                continue

        return results
