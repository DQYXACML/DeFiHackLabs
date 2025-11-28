"""
ABI函数分析器

基于合约ABI的函数签名分析,识别DeFi协议类型。
"""

import logging
from enum import Enum
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from collections import Counter

logger = logging.getLogger(__name__)


class ProtocolType(Enum):
    """DeFi协议类型"""
    VAULT = "vault"
    AMM = "amm"
    LENDING = "lending"
    STAKING = "staking"
    BRIDGE = "bridge"
    NFT_MARKETPLACE = "nft_marketplace"
    GOVERNANCE = "governance"
    ERC20 = "erc20"
    UNKNOWN = "unknown"


@dataclass
class FunctionSignature:
    """函数签名"""
    name: str
    inputs: List[str]
    outputs: List[str]
    stateMutability: str
    function_type: str = "function"


class ABIFunctionAnalyzer:
    """
    ABI函数签名分析器

    通过分析合约ABI中的函数名称、参数、返回值,
    识别协议类型和核心功能。
    """

    # 协议特征函数库 (函数名 -> 协议类型)
    PROTOCOL_FUNCTION_SIGNATURES = {
        # Vault/Wrapper协议
        ProtocolType.VAULT: {
            "core": ["deposit", "withdraw", "mint", "redeem", "convertToShares", "convertToAssets"],
            "supporting": ["totalAssets", "totalSupply", "asset", "previewDeposit", "previewMint"],
            "admin": ["setVaultFee", "harvestRewards", "rebalance"]
        },

        # AMM/DEX协议
        ProtocolType.AMM: {
            "core": ["swap", "addLiquidity", "removeLiquidity", "swapExactTokensForTokens"],
            "supporting": ["getReserves", "getAmountOut", "getAmountIn", "quote", "price0CumulativeLast"],
            "admin": ["setFee", "sync", "skim"]
        },

        # Lending协议
        ProtocolType.LENDING: {
            "core": ["borrow", "repay", "liquidate", "supply", "redeem"],
            "supporting": [
                "getAccountLiquidity",
                "getBorrowBalance",
                "getSupplyBalance",
                "borrowRatePerBlock",
                "supplyRatePerBlock",
                "utilizationRate"
            ],
            "admin": ["_setCollateralFactor", "_setReserveFactor", "_acceptAdmin"]
        },

        # Staking协议
        ProtocolType.STAKING: {
            "core": ["stake", "unstake", "withdraw", "claimRewards", "compound"],
            "supporting": [
                "earned",
                "rewardPerToken",
                "balanceOf",
                "totalStaked",
                "stakingToken",
                "rewardsToken"
            ],
            "admin": ["setRewardsDuration", "notifyRewardAmount"]
        },

        # Bridge协议
        ProtocolType.BRIDGE: {
            "core": ["bridge", "lock", "unlock", "relay", "executeTransaction"],
            "supporting": [
                "getChainId",
                "estimateFee",
                "validateSignature",
                "isTransactionExecuted"
            ],
            "admin": ["addValidator", "removeValidator", "setThreshold"]
        },

        # NFT Marketplace
        ProtocolType.NFT_MARKETPLACE: {
            "core": ["listItem", "buyItem", "cancelListing", "makeOffer", "acceptOffer"],
            "supporting": ["getListingPrice", "getListing", "getOffer"],
            "admin": ["setMarketplaceFee", "withdraw"]
        },

        # Governance
        ProtocolType.GOVERNANCE: {
            "core": ["propose", "castVote", "queue", "execute", "cancel"],
            "supporting": [
                "getProposal",
                "getVotes",
                "getPastVotes",
                "quorum",
                "proposalThreshold"
            ],
            "admin": ["__acceptAdmin", "__queueSetTimelockPendingAdmin"]
        },

        # ERC20基础代币
        ProtocolType.ERC20: {
            "core": ["transfer", "approve", "transferFrom"],
            "supporting": ["balanceOf", "allowance", "totalSupply", "decimals", "symbol", "name"],
            "admin": ["mint", "burn", "pause", "unpause"]
        }
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.ABIFunctionAnalyzer')

    def analyze_abi(self, abi: List[Dict]) -> Dict:
        """
        分析ABI并返回协议类型检测结果

        Args:
            abi: 合约ABI (JSON格式)

        Returns:
            {
                "protocol_scores": {"vault": 0.8, "amm": 0.3, ...},
                "detected_type": ProtocolType.VAULT,
                "confidence": 0.85,
                "matched_functions": {...},
                "evidence": [...]
            }
        """
        # 1. 提取函数签名
        functions = self._extract_functions(abi)

        # 2. 计算每种协议类型的匹配分数
        protocol_scores = {}
        matched_functions = {}
        evidence = []

        for protocol_type, function_groups in self.PROTOCOL_FUNCTION_SIGNATURES.items():
            score, matches = self._calculate_protocol_score(functions, function_groups)
            protocol_scores[protocol_type.value] = score
            matched_functions[protocol_type.value] = matches

            if score > 0:
                evidence.append(f"{protocol_type.value}: 匹配 {len(matches)} 个函数 (score={score:.2f})")

        # 3. 确定最佳匹配
        best_protocol = max(protocol_scores.items(), key=lambda x: x[1])
        detected_type = ProtocolType(best_protocol[0])
        confidence = best_protocol[1]

        self.logger.info(f"协议检测结果: {detected_type.value} (confidence={confidence:.2f})")

        return {
            "protocol_scores": protocol_scores,
            "detected_type": detected_type,
            "confidence": confidence,
            "matched_functions": matched_functions,
            "evidence": evidence,
            "total_functions": len(functions)
        }

    def _extract_functions(self, abi: List[Dict]) -> List[FunctionSignature]:
        """从ABI提取函数签名"""
        functions = []

        for item in abi:
            if item.get("type") == "function":
                func = FunctionSignature(
                    name=item.get("name", ""),
                    inputs=[inp.get("type", "") for inp in item.get("inputs", [])],
                    outputs=[out.get("type", "") for out in item.get("outputs", [])],
                    stateMutability=item.get("stateMutability", "nonpayable"),
                    function_type="function"
                )
                functions.append(func)

        self.logger.debug(f"提取到 {len(functions)} 个函数")
        return functions

    def _calculate_protocol_score(
        self,
        functions: List[FunctionSignature],
        function_groups: Dict[str, List[str]]
    ) -> tuple[float, List[str]]:
        """
        计算协议匹配分数

        评分规则:
        - core函数匹配: 每个 +0.3
        - supporting函数匹配: 每个 +0.1
        - admin函数匹配: 每个 +0.05

        Returns:
            (score, matched_function_names)
        """
        function_names = set(f.name for f in functions)
        matched = []
        score = 0.0

        # 检查core函数
        core_matches = function_names.intersection(set(function_groups.get("core", [])))
        score += len(core_matches) * 0.3
        matched.extend(core_matches)

        # 检查supporting函数
        supporting_matches = function_names.intersection(set(function_groups.get("supporting", [])))
        score += len(supporting_matches) * 0.1
        matched.extend(supporting_matches)

        # 检查admin函数
        admin_matches = function_names.intersection(set(function_groups.get("admin", [])))
        score += len(admin_matches) * 0.05
        matched.extend(admin_matches)

        # 标准化分数到[0, 1]
        score = min(score, 1.0)

        return score, matched

    def detect_erc_standards(self, abi: List[Dict]) -> List[str]:
        """
        检测ERC标准实现

        Returns:
            实现的ERC标准列表 (如 ["ERC20", "ERC4626"])
        """
        standards = []
        function_names = set(
            item.get("name", "")
            for item in abi
            if item.get("type") == "function"
        )

        # ERC20标准
        erc20_required = {"totalSupply", "balanceOf", "transfer", "transferFrom", "approve", "allowance"}
        if erc20_required.issubset(function_names):
            standards.append("ERC20")

        # ERC4626 Vault标准
        erc4626_required = {
            "asset", "totalAssets", "convertToShares", "convertToAssets",
            "maxDeposit", "previewDeposit", "deposit",
            "maxMint", "previewMint", "mint",
            "maxWithdraw", "previewWithdraw", "withdraw",
            "maxRedeem", "previewRedeem", "redeem"
        }
        if erc4626_required.issubset(function_names):
            standards.append("ERC4626")

        # ERC721 NFT标准
        erc721_required = {
            "balanceOf", "ownerOf", "safeTransferFrom", "transferFrom",
            "approve", "setApprovalForAll", "getApproved", "isApprovedForAll"
        }
        if erc721_required.issubset(function_names):
            standards.append("ERC721")

        # ERC1155 Multi-Token标准
        erc1155_required = {
            "balanceOf", "balanceOfBatch", "setApprovalForAll",
            "isApprovedForAll", "safeTransferFrom", "safeBatchTransferFrom"
        }
        if erc1155_required.issubset(function_names):
            standards.append("ERC1155")

        self.logger.info(f"检测到ERC标准: {standards}")
        return standards

    def get_critical_functions(self, abi: List[Dict]) -> Dict[str, List[str]]:
        """
        识别关键函数 (高风险、高价值)

        返回:
            {
                "value_transfer": [...],  # 涉及资产转移的函数
                "permission": [...],      # 权限管理函数
                "price_sensitive": [...]  # 价格敏感函数
            }
        """
        critical = {
            "value_transfer": [],
            "permission": [],
            "price_sensitive": []
        }

        value_keywords = ["transfer", "withdraw", "deposit", "mint", "burn", "swap", "borrow", "repay"]
        permission_keywords = ["admin", "owner", "pause", "approve", "auth"]
        price_keywords = ["price", "oracle", "rate", "exchange", "quote"]

        for item in abi:
            if item.get("type") != "function":
                continue

            name = item.get("name", "").lower()

            # 检查资产转移
            if any(kw in name for kw in value_keywords):
                critical["value_transfer"].append(item["name"])

            # 检查权限管理
            if any(kw in name for kw in permission_keywords):
                critical["permission"].append(item["name"])

            # 检查价格相关
            if any(kw in name for kw in price_keywords):
                critical["price_sensitive"].append(item["name"])

        return critical
