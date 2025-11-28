#!/usr/bin/env python3
"""
Storage Slot Relationship Invariant Generator

This module generates protocol-level business logic invariants based on
storage slot relationships, rather than execution behavior.

Key Innovation:
- Detects WHAT storage slots mean (totalSupply, balances, reserves)
- Finds mathematical relationships between slots (ratios, products, sums)
- Generates invariants that capture DeFi protocol semantics

Example Generated Invariants:
- Vault: share_price_stability (reserves/totalSupply bounded)
- AMM: constant_product (reserve0 * reserve1 ≈ K)
- Lending: collateralization_ratio (collateral/debt >= minRatio)

Author: Claude Code
Version: 1.0.0
"""

import logging
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Any, Set
from enum import Enum
from pathlib import Path

# ============================================================================
# Configuration
# ============================================================================

LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# ============================================================================
# Enums & Constants
# ============================================================================

class ProtocolType(Enum):
    """DeFi protocol classification"""
    VAULT = "vault"              # Share token backed by underlying asset
    AMM = "amm"                  # Automated market maker with reserves
    LENDING = "lending"          # Collateral + debt system
    STAKING = "staking"          # Staking rewards accumulation
    ERC20 = "erc20"             # Simple ERC20 token
    UNKNOWN = "unknown"

class SlotSemanticType(Enum):
    """Storage slot semantic meanings"""
    TOTAL_SUPPLY = "totalSupply"
    BALANCE_MAPPING = "balance_mapping"
    RESERVE = "reserve"
    DEBT = "debt"
    COLLATERAL = "collateral"
    ADDRESS_REFERENCE = "address_reference"
    PRICE_ORACLE = "price_oracle"
    TIMESTAMP = "timestamp"
    TOKEN_AMOUNT = "token_amount"
    UNKNOWN = "unknown"

# ERC20 standard layout (most common)
ERC20_STANDARD_SLOTS = {
    "2": SlotSemanticType.TOTAL_SUPPLY,
    "3": SlotSemanticType.BALANCE_MAPPING,  # Actually the slot for mapping base
}

# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class StorageSlot:
    """Represents a storage slot with semantic meaning"""
    slot_number: str                    # Hex string of slot number
    contract_address: str               # Contract this slot belongs to
    value: str                          # Hex value at this slot
    semantic_type: SlotSemanticType
    confidence: float                   # 0.0-1.0 confidence in semantic type
    metadata: Dict[str, Any] = field(default_factory=dict)

    def value_as_int(self) -> int:
        """Convert hex value to integer"""
        return int(self.value, 16) if self.value.startswith('0x') else int(self.value)

    def value_as_address(self) -> Optional[str]:
        """Extract address if this is an address slot"""
        val = self.value_as_int()
        if val < 2**160 and val > 0:
            return '0x' + self.value[-40:].lower()
        return None

@dataclass
class StorageRelationship:
    """Mathematical relationship between storage slots"""
    relationship_type: str              # sum, ratio, product, bounded_change
    involved_slots: List[StorageSlot]
    formula: str                        # Human-readable formula
    threshold: float                    # Acceptable deviation
    confidence: float                   # Confidence this relationship exists
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class StorageInvariant:
    """A monitorable invariant based on storage relationships"""
    id: str
    type: str                           # share_price_stability, constant_product, etc.
    severity: str                       # critical, high, medium, low
    description: str
    formula: str
    contracts: List[str]                # Contract addresses involved
    slots: Dict[str, Any]               # Slot references for monitoring
    threshold: float
    reason: str
    violation_impact: str
    confidence: float = 0.9
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ContractState:
    """State of a contract from attack_state.json"""
    address: str
    balance_wei: str
    nonce: int
    code: str
    code_size: int
    is_contract: bool
    storage: Dict[str, str]
    name: str = "Unknown"

# ============================================================================
# Slot Analyzer: Identify storage slot semantics
# ============================================================================

class SlotAnalyzer:
    """Analyzes storage slots to identify their semantic meaning"""

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.SlotAnalyzer')

    def analyze_contract_slots(self, contract: ContractState) -> List[StorageSlot]:
        """
        Analyze all storage slots in a contract to identify their semantics

        Args:
            contract: ContractState with storage data

        Returns:
            List of StorageSlots with semantic types identified
        """
        slots = []

        for slot_num, value in contract.storage.items():
            semantic = self._infer_semantic_type(slot_num, value, contract)

            slot = StorageSlot(
                slot_number=slot_num,
                contract_address=contract.address,
                value=value,
                semantic_type=semantic['type'],
                confidence=semantic['confidence'],
                metadata=semantic.get('metadata', {})
            )
            slots.append(slot)

            self.logger.debug(f"Slot {slot_num[:10]}... -> {semantic['type'].value} (conf: {semantic['confidence']:.2f})")

        return slots

    def _infer_semantic_type(self, slot: str, value: str, contract: ContractState) -> Dict[str, Any]:
        """
        Use heuristics to infer what a storage slot represents

        Heuristics:
        1. Slot position (ERC20 standard: slot 2 = totalSupply)
        2. Value range (10^18-10^27 = token amounts)
        3. Slot number size (>10^70 = mapping hash)
        4. Address detection (value < 2^160)
        """
        result = {
            'type': SlotSemanticType.UNKNOWN,
            'confidence': 0.1,
            'metadata': {}
        }

        # Heuristic 1: Standard ERC20 slot positions
        if slot in ERC20_STANDARD_SLOTS:
            result['type'] = ERC20_STANDARD_SLOTS[slot]
            result['confidence'] = 0.8
            result['metadata']['reason'] = 'ERC20 standard slot position'
            return result

        # Convert value to int for analysis
        try:
            value_int = int(value, 16) if value.startswith('0x') else int(value)
            slot_int = int(slot, 16) if slot.startswith('0x') else int(slot)
        except:
            return result

        # Heuristic 2: Very large slot numbers = mapping
        if slot_int > 10**70:
            result['type'] = SlotSemanticType.BALANCE_MAPPING
            result['confidence'] = 0.7
            result['metadata']['reason'] = 'Large slot number suggests keccak256 mapping'
            return result

        # Heuristic 3: Value is an address
        if 0 < value_int < 2**160:
            result['type'] = SlotSemanticType.ADDRESS_REFERENCE
            result['confidence'] = 0.75
            result['metadata']['reason'] = 'Value in address range'
            result['metadata']['possible_address'] = '0x' + value[-40:]
            return result

        # Heuristic 4: Value in token amount range
        if 10**18 <= value_int <= 10**27:
            result['type'] = SlotSemanticType.TOKEN_AMOUNT
            result['confidence'] = 0.6
            result['metadata']['reason'] = 'Value in token amount range (1e18-1e27)'
            return result

        # Heuristic 5: Small values could be decimals, counters, etc.
        if 0 < value_int < 100:
            result['type'] = SlotSemanticType.UNKNOWN
            result['confidence'] = 0.3
            result['metadata']['reason'] = 'Small value - could be decimals, counter, etc.'
            return result

        return result

# ============================================================================
# Protocol Detector: Classify DeFi protocol type
# ============================================================================

class ProtocolDetector:
    """Detects what type of DeFi protocol we're analyzing"""

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.ProtocolDetector')

    def detect_protocol_type(self,
                            all_slots: List[StorageSlot],
                            all_contracts: Dict[str, ContractState]) -> Dict[str, Any]:
        """
        Detect protocol type based on storage slot patterns

        Returns:
            Dict with:
            - 'type': ProtocolType
            - 'confidence': float
            - 'evidence': List[str]
            - 'primary_contract': str (address)
        """
        # Group slots by contract
        slots_by_contract = self._group_by_contract(all_slots)

        # Check for each protocol pattern
        vault_result = self._check_vault_pattern(slots_by_contract, all_contracts)
        amm_result = self._check_amm_pattern(slots_by_contract, all_contracts)

        # Return highest confidence result
        results = [vault_result, amm_result]
        best_result = max(results, key=lambda x: x['confidence'])

        self.logger.info(f"Detected protocol type: {best_result['type'].value} (confidence: {best_result['confidence']:.2f})")
        return best_result

    def _group_by_contract(self, slots: List[StorageSlot]) -> Dict[str, List[StorageSlot]]:
        """Group slots by their contract address"""
        grouped = {}
        for slot in slots:
            if slot.contract_address not in grouped:
                grouped[slot.contract_address] = []
            grouped[slot.contract_address].append(slot)
        return grouped

    def _check_vault_pattern(self,
                            slots_by_contract: Dict[str, List[StorageSlot]],
                            all_contracts: Dict[str, ContractState]) -> Dict[str, Any]:
        """
        Check if this is a vault/wrapper token pattern

        Vault pattern:
        - Has totalSupply (share token)
        - References another token address (underlying asset)
        - Referenced token is also a contract with storage
        """
        evidence = []

        # Create case-insensitive lookup for contracts
        contracts_lower = {addr.lower(): addr for addr in all_contracts.keys()}

        for contract_addr, slots in slots_by_contract.items():
            has_total_supply = any(
                s.semantic_type == SlotSemanticType.TOTAL_SUPPLY
                for s in slots
            )

            if not has_total_supply:
                continue

            evidence.append(f"Contract {contract_addr[:10]}... has totalSupply at slot 2")

            # Find address references
            address_refs = [
                s for s in slots
                if s.semantic_type == SlotSemanticType.ADDRESS_REFERENCE
            ]

            if address_refs:
                evidence.append(f"Found {len(address_refs)} address references in storage")

                # Check if referenced addresses are other contracts in our set
                for addr_slot in address_refs:
                    ref_addr = addr_slot.value_as_address()
                    if ref_addr:
                        ref_addr_lower = ref_addr.lower()

                        # Check if this address is in our contracts
                        if ref_addr_lower in contracts_lower:
                            actual_addr = contracts_lower[ref_addr_lower]
                            ref_contract = all_contracts[actual_addr]

                            evidence.append(f"References contract {ref_addr[:10]}... (slot: {addr_slot.slot_number[:10]}...)")

                            # Check if referenced contract is ERC20 (has code and totalSupply)
                            if ref_contract.is_contract and ref_contract.code_size > 1000:
                                # Check if referenced contract also has totalSupply
                                ref_has_supply = '2' in ref_contract.storage or '0x2' in ref_contract.storage

                                if ref_has_supply:
                                    evidence.append(f"Referenced contract appears to be ERC20 token (has code + totalSupply)")

                                    return {
                                        'type': ProtocolType.VAULT,
                                        'confidence': 0.85,
                                        'evidence': evidence,
                                        'primary_contract': contract_addr,
                                        'metadata': {
                                            'share_token': contract_addr,
                                            'underlying_token': actual_addr
                                        }
                                    }
                                else:
                                    evidence.append(f"Referenced contract is large but doesn't look like ERC20")

            # Alternative: Check for balance mapping patterns
            # If a contract has totalSupply and balance mappings, and there's another ERC20 in the set
            # this could still be a vault
            if has_total_supply:
                # Look for other ERC20s in the set
                other_erc20s = [
                    addr for addr, contract in all_contracts.items()
                    if addr.lower() != contract_addr.lower()
                    and contract.is_contract
                    and ('2' in contract.storage or '0x2' in contract.storage)
                    and contract.code_size > 1000
                ]

                if other_erc20s:
                    evidence.append(f"Found {len(other_erc20s)} other ERC20 contracts in the set")

                    # This might be a vault - return with lower confidence
                    return {
                        'type': ProtocolType.VAULT,
                        'confidence': 0.65,
                        'evidence': evidence,
                        'primary_contract': contract_addr,
                        'metadata': {
                            'share_token': contract_addr,
                            'underlying_token': other_erc20s[0],
                            'detection_method': 'inferred_from_multiple_erc20s'
                        }
                    }

        return {
            'type': ProtocolType.VAULT,
            'confidence': 0.0,
            'evidence': [],
            'primary_contract': None
        }

    def _check_amm_pattern(self,
                          slots_by_contract: Dict[str, List[StorageSlot]],
                          all_contracts: Dict[str, ContractState]) -> Dict[str, Any]:
        """
        Check if this is an AMM (liquidity pool) pattern

        AMM pattern:
        - Has multiple large value slots (reserves)
        - Slots are in consecutive positions
        - Has totalSupply (LP tokens)
        """
        evidence = []

        for contract_addr, slots in slots_by_contract.items():
            # Find consecutive slots with large values
            large_value_slots = [
                s for s in slots
                if s.semantic_type == SlotSemanticType.TOKEN_AMOUNT
            ]

            if len(large_value_slots) >= 2:
                evidence.append(f"Found {len(large_value_slots)} large value slots (potential reserves)")

                has_total_supply = any(
                    s.semantic_type == SlotSemanticType.TOTAL_SUPPLY
                    for s in slots
                )

                if has_total_supply:
                    evidence.append("Has totalSupply (LP token shares)")

                    return {
                        'type': ProtocolType.AMM,
                        'confidence': 0.75,
                        'evidence': evidence,
                        'primary_contract': contract_addr,
                        'metadata': {
                            'reserve_slots': [s.slot_number for s in large_value_slots]
                        }
                    }

        return {
            'type': ProtocolType.AMM,
            'confidence': 0.0,
            'evidence': [],
            'primary_contract': None
        }

# ============================================================================
# Relationship Detector: Find mathematical relationships
# ============================================================================

class RelationshipDetector:
    """Detects mathematical relationships between storage slots"""

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.RelationshipDetector')

    def find_relationships(
        self,
        slots: List[StorageSlot],
        protocol_info: Dict[str, Any],
        all_contracts: Dict[str, ContractState],
        storage_diffs: Optional[Dict[str, Dict]] = None
    ) -> List[StorageRelationship]:
        """
        Find mathematical relationships between slots based on protocol type

        Args:
            slots: All analyzed storage slots
            protocol_info: Result from ProtocolDetector
            all_contracts: All contract states
            storage_diffs: Storage changes from attack (optional)

        Returns:
            List of detected storage relationships
        """
        relationships = []
        protocol_type = protocol_info['type']

        if protocol_type == ProtocolType.VAULT:
            relationships.extend(
                self._detect_vault_relationships(
                    slots, protocol_info, all_contracts, storage_diffs
                )
            )
        elif protocol_type == ProtocolType.AMM:
            relationships.extend(self._detect_amm_relationships(slots, protocol_info))

        # Universal: bounded change rate for critical slots
        relationships.extend(self._detect_bounded_changes(slots, storage_diffs))

        self.logger.info(f"Detected {len(relationships)} storage relationships")
        return relationships

    def _detect_vault_relationships(self,
                                   slots: List[StorageSlot],
                                   protocol_info: Dict[str, Any],
                                   all_contracts: Dict[str, ContractState],
                                   storage_diffs: Optional[Dict[str, Dict]] = None) -> List[StorageRelationship]:
        """
        Detect vault-specific relationships:
        - Share price stability: (reserves / totalSupply) should be stable
        - Supply backing: totalSupply <= reserves * leverage_ratio

        支持基于攻击 diff 的动态阈值计算

        Args:
            slots: 所有槽位
            protocol_info: 协议信息
            all_contracts: 所有合约状态
            storage_diffs: 攻击前后的存储变化（可选）
        """
        relationships = []

        share_token_addr = protocol_info.get('metadata', {}).get('share_token')
        underlying_token_addr = protocol_info.get('metadata', {}).get('underlying_token')

        if not (share_token_addr and underlying_token_addr):
            return relationships

        # Find totalSupply slot
        total_supply_slot = next(
            (s for s in slots
             if s.semantic_type == SlotSemanticType.TOTAL_SUPPLY
             and s.contract_address.lower() == share_token_addr.lower()),
            None
        )

        if total_supply_slot:
            # 检查是否有 totalSupply 的实际变化数据
            share_price_threshold = 0.05  # 默认5%
            threshold_method = 'static'
            observed_change = None

            if storage_diffs:
                addr = total_supply_slot.contract_address
                slot_num = total_supply_slot.slot_number

                if addr in storage_diffs:
                    slot_diffs = storage_diffs[addr].get('slot_diffs', {})

                    if slot_num in slot_diffs:
                        diff_data = slot_diffs[slot_num]

                        # 如果是数值变化，使用观察到的变化率
                        if 'change_rate' in diff_data and diff_data['change_rate'] != float('inf'):
                            observed_change = diff_data['change_rate']

                            # 动态阈值 = 观察到的变化 × 安全系数 (0.5)
                            share_price_threshold = observed_change * 0.5

                            # 限制最小阈值为 1%
                            share_price_threshold = max(share_price_threshold, 0.01)

                            # 限制最大阈值为 50%
                            share_price_threshold = min(share_price_threshold, 0.5)

                            threshold_method = 'attack_based'

                            self.logger.debug(
                                f"  Vault share price 动态阈值: {total_supply_slot.contract_address[:10]}... "
                                f"观察变化 {observed_change:.2%} → 阈值 {share_price_threshold:.2%}"
                            )

            # Relationship 1: Share price stability
            rel = StorageRelationship(
                relationship_type='share_price_ratio',
                involved_slots=[total_supply_slot],
                formula=f'|(reserves/totalSupply)_after - (reserves/totalSupply)_before| / (reserves/totalSupply)_before',
                threshold=share_price_threshold,
                confidence=0.9 if threshold_method == 'attack_based' else 0.85,
                metadata={
                    'share_token': share_token_addr,
                    'underlying_token': underlying_token_addr,
                    'reserves_query': f'{underlying_token_addr}.balanceOf({share_token_addr})',
                    'threshold_method': threshold_method,
                    'observed_attack_change': observed_change,
                    'safety_coefficient': 0.5 if threshold_method == 'attack_based' else None
                }
            )
            relationships.append(rel)

            # Relationship 2: Supply backing consistency
            # 此不变量通常是绝对约束，不需要动态调整
            rel2 = StorageRelationship(
                relationship_type='supply_backing',
                involved_slots=[total_supply_slot],
                formula='totalSupply <= reserves * max_leverage_ratio',
                threshold=1.1,  # 110% max (10% tolerance)
                confidence=0.85,
                metadata={
                    'share_token': share_token_addr,
                    'underlying_token': underlying_token_addr,
                    'description': 'Total shares should not exceed underlying assets',
                    'note': 'This is an absolute constraint, not dynamically adjusted'
                }
            )
            relationships.append(rel2)

        return relationships

    def _detect_amm_relationships(self,
                                 slots: List[StorageSlot],
                                 protocol_info: Dict[str, Any]) -> List[StorageRelationship]:
        """
        Detect AMM-specific relationships:
        - Constant product: reserve0 * reserve1 ≈ K
        - Reserve ratio bounds
        """
        relationships = []

        reserve_slot_numbers = protocol_info.get('metadata', {}).get('reserve_slots', [])

        if len(reserve_slot_numbers) >= 2:
            reserve_slots = [
                s for s in slots
                if s.slot_number in reserve_slot_numbers[:2]
            ]

            if len(reserve_slots) == 2:
                # Constant product invariant
                rel = StorageRelationship(
                    relationship_type='constant_product',
                    involved_slots=reserve_slots,
                    formula='reserve0 * reserve1 ≈ K (constant)',
                    threshold=0.001,  # 0.1% deviation allowed (for fees)
                    confidence=0.9,
                    metadata={
                        'reserve0_slot': reserve_slots[0].slot_number,
                        'reserve1_slot': reserve_slots[1].slot_number
                    }
                )
                relationships.append(rel)

        return relationships

    def _detect_bounded_changes(
        self,
        slots: List[StorageSlot],
        storage_diffs: Optional[Dict[str, Dict]] = None
    ) -> List[StorageRelationship]:
        """
        Detect bounded change rate constraints for critical slots

        支持基于攻击 diff 的动态阈值计算

        Any totalSupply or reserve should not change dramatically in one tx

        Args:
            slots: 所有槽位
            storage_diffs: 攻击前后的存储变化（可选）
        """
        relationships = []

        critical_slots = [
            s for s in slots
            if s.semantic_type in [
                SlotSemanticType.TOTAL_SUPPLY,
                SlotSemanticType.RESERVE,
                SlotSemanticType.TOKEN_AMOUNT
            ]
        ]

        for slot in critical_slots:
            # 默认阈值
            threshold = 0.5  # 50% max change per transaction
            threshold_method = 'static'
            observed_change = None

            # 如果有 diff 信息，尝试使用动态阈值
            if storage_diffs:
                addr = slot.contract_address
                slot_num = slot.slot_number

                if addr in storage_diffs:
                    slot_diffs = storage_diffs[addr].get('slot_diffs', {})

                    if slot_num in slot_diffs:
                        diff_data = slot_diffs[slot_num]

                        # 如果是数值变化，使用观察到的变化率
                        if 'change_rate' in diff_data and diff_data['change_rate'] != float('inf'):
                            observed_change = diff_data['change_rate']

                            # 动态阈值 = 观察到的变化 × 安全系数 (0.5)
                            threshold = observed_change * 0.5

                            # 限制最小阈值为 1%
                            threshold = max(threshold, 0.01)

                            # 限制最大阈值为 100% (避免过于宽松)
                            threshold = min(threshold, 1.0)

                            threshold_method = 'attack_based'

                            self.logger.debug(
                                f"  动态阈值: {slot.contract_address[:10]}.../{slot_num[:8]}... "
                                f"观察变化 {observed_change:.2%} → 阈值 {threshold:.2%}"
                            )

            rel = StorageRelationship(
                relationship_type='bounded_change',
                involved_slots=[slot],
                formula=f'|slot_{slot.slot_number[:8]}_after - slot_{slot.slot_number[:8]}_before| / slot_{slot.slot_number[:8]}_before',
                threshold=threshold,
                confidence=0.8 if threshold_method == 'attack_based' else 0.7,
                metadata={
                    'slot_semantic': slot.semantic_type.value,
                    'contract': slot.contract_address,
                    'threshold_method': threshold_method,
                    'observed_attack_change': observed_change,
                    'safety_coefficient': 0.5 if threshold_method == 'attack_based' else None
                }
            )
            relationships.append(rel)

        return relationships

# ============================================================================
# Storage Invariant Generator: Convert relationships to invariants
# ============================================================================

class StorageInvariantGenerator:
    """Generates monitorable invariants from storage relationships"""

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.StorageInvariantGenerator')
        self.invariant_id_counter = 1

    def generate_invariants(self,
                           relationships: List[StorageRelationship],
                           protocol_info: Dict[str, Any]) -> List[StorageInvariant]:
        """
        Convert storage relationships into monitorable invariants

        Args:
            relationships: Detected storage relationships
            protocol_info: Protocol type and metadata

        Returns:
            List of storage invariants
        """
        invariants = []

        for rel in relationships:
            if rel.relationship_type == 'share_price_ratio':
                inv = self._create_share_price_invariant(rel, protocol_info)
                invariants.append(inv)

            elif rel.relationship_type == 'supply_backing':
                inv = self._create_supply_backing_invariant(rel, protocol_info)
                invariants.append(inv)

            elif rel.relationship_type == 'constant_product':
                inv = self._create_constant_product_invariant(rel, protocol_info)
                invariants.append(inv)

            elif rel.relationship_type == 'bounded_change':
                inv = self._create_bounded_change_invariant(rel, protocol_info)
                invariants.append(inv)

        self.logger.info(f"Generated {len(invariants)} storage invariants")
        return invariants

    def _create_share_price_invariant(self,
                                     rel: StorageRelationship,
                                     protocol_info: Dict[str, Any]) -> StorageInvariant:
        """Create share price stability invariant for vaults"""
        total_supply_slot = rel.involved_slots[0]

        return StorageInvariant(
            id=f"SINV_{self._next_id():03d}",
            type='share_price_stability',
            severity='critical',
            description='Vault share price must not change more than 5% per transaction',
            formula=rel.formula + ' <= 0.05',
            contracts=[
                rel.metadata['share_token'],
                rel.metadata['underlying_token']
            ],
            slots={
                'totalSupply_slot': total_supply_slot.slot_number,
                'totalSupply_contract': total_supply_slot.contract_address,
                'reserves_contract': rel.metadata['underlying_token'],
                'reserves_query': rel.metadata['reserves_query']
            },
            threshold=rel.threshold,
            reason='Vault pattern detected. Share price manipulation indicates attack.',
            violation_impact='Allows attacker to mint underpriced shares and drain underlying assets',
            confidence=rel.confidence,
            metadata={
                'protocol_type': protocol_info['type'].value,
                'relationship_type': rel.relationship_type
            }
        )

    def _create_supply_backing_invariant(self,
                                        rel: StorageRelationship,
                                        protocol_info: Dict[str, Any]) -> StorageInvariant:
        """Create supply backing consistency invariant"""
        total_supply_slot = rel.involved_slots[0]

        return StorageInvariant(
            id=f"SINV_{self._next_id():03d}",
            type='supply_backing_consistency',
            severity='critical',
            description='Total supply must be backed by proportional underlying reserves',
            formula=rel.formula,
            contracts=[
                rel.metadata['share_token'],
                rel.metadata['underlying_token']
            ],
            slots={
                'totalSupply_slot': total_supply_slot.slot_number,
                'totalSupply_contract': total_supply_slot.contract_address,
                'underlying_contract': rel.metadata['underlying_token']
            },
            threshold=rel.threshold,
            reason='Vault shares should not exceed underlying assets by more than 10%',
            violation_impact='Indicates phantom shares minted without backing',
            confidence=rel.confidence,
            metadata=rel.metadata
        )

    def _create_constant_product_invariant(self,
                                          rel: StorageRelationship,
                                          protocol_info: Dict[str, Any]) -> StorageInvariant:
        """Create constant product invariant for AMMs"""
        return StorageInvariant(
            id=f"SINV_{self._next_id():03d}",
            type='constant_product',
            severity='critical',
            description='AMM constant product must remain stable (reserve0 * reserve1 ≈ K)',
            formula=rel.formula,
            contracts=[rel.involved_slots[0].contract_address],
            slots={
                'reserve0_slot': rel.involved_slots[0].slot_number,
                'reserve1_slot': rel.involved_slots[1].slot_number,
                'contract': rel.involved_slots[0].contract_address
            },
            threshold=rel.threshold,
            reason='AMM invariant violation indicates price manipulation or flash loan attack',
            violation_impact='Allows attacker to manipulate pool price and extract value',
            confidence=rel.confidence,
            metadata=rel.metadata
        )

    def _create_bounded_change_invariant(self,
                                        rel: StorageRelationship,
                                        protocol_info: Dict[str, Any]) -> StorageInvariant:
        """Create bounded change rate invariant"""
        slot = rel.involved_slots[0]

        return StorageInvariant(
            id=f"SINV_{self._next_id():03d}",
            type='bounded_change_rate',
            severity='high',
            description=f'{slot.semantic_type.value} should not change more than 50% in single transaction',
            formula=rel.formula + ' <= 0.5',
            contracts=[slot.contract_address],
            slots={
                'monitored_slot': slot.slot_number,
                'contract': slot.contract_address,
                'semantic_type': slot.semantic_type.value
            },
            threshold=rel.threshold,
            reason=f'Large {slot.semantic_type.value} changes indicate potential manipulation',
            violation_impact='Flash mint attacks, accounting manipulation, or reentrancy',
            confidence=rel.confidence,
            metadata=rel.metadata
        )

    def _next_id(self) -> int:
        """Get next invariant ID"""
        id_val = self.invariant_id_counter
        self.invariant_id_counter += 1
        return id_val

# ============================================================================
# Main Orchestrator
# ============================================================================

class StorageInvariantAnalyzer:
    """Main orchestrator for storage invariant analysis"""

    def __init__(self):
        self.slot_analyzer = SlotAnalyzer()
        self.protocol_detector = ProtocolDetector()
        self.relationship_detector = RelationshipDetector()
        self.invariant_generator = StorageInvariantGenerator()
        self.logger = logging.getLogger(__name__ + '.Analyzer')

    def analyze(
        self,
        contracts_before: Dict[str, ContractState],
        contracts_after: Optional[Dict[str, ContractState]] = None
    ) -> Dict[str, Any]:
        """
        Main analysis pipeline (支持攻击前后状态对比)

        Args:
            contracts_before: 攻击前的合约状态字典
            contracts_after: 攻击后的合约状态字典 (可选)

        Returns:
            Dictionary containing:
            - storage_slots: List of analyzed slots
            - protocol_info: Detected protocol type and metadata
            - relationships: Detected storage relationships
            - invariants: Generated invariants
            - storage_diffs: Storage changes (if contracts_after provided)
        """
        self.logger.info("="*80)
        self.logger.info("Storage Slot Relationship Analysis")
        if contracts_after:
            self.logger.info("模式: 攻击前后对比分析")
        else:
            self.logger.info("模式: 单状态分析")
        self.logger.info("="*80)

        # Step 0: 如果有 after 状态，计算 diff
        storage_diffs = {}
        if contracts_after:
            self.logger.info("\n[0/5] 计算存储槽变化...")
            storage_diffs = self._compute_storage_diffs(contracts_before, contracts_after)

            total_changed_slots = sum(len(diff['slot_diffs']) for diff in storage_diffs.values())
            self.logger.info(f"检测到 {len(storage_diffs)} 个合约有存储变化")
            self.logger.info(f"总计 {total_changed_slots} 个槽位发生变化")

        # Step 1: Analyze all storage slots (基于 before 状态)
        step_num = 1 if not contracts_after else 1
        total_steps = 4 if not contracts_after else 5
        self.logger.info(f"\n[{step_num}/{total_steps}] Analyzing storage slots...")
        all_slots = []
        for addr, contract in contracts_before.items():
            if contract.is_contract and contract.storage:
                slots = self.slot_analyzer.analyze_contract_slots(contract)
                all_slots.extend(slots)

        self.logger.info(f"Analyzed {len(all_slots)} storage slots across {len([c for c in contracts_before.values() if c.is_contract])} contracts")

        # Step 2: Detect protocol type
        step_num += 1
        self.logger.info(f"\n[{step_num}/{total_steps}] Detecting protocol type...")
        protocol_info = self.protocol_detector.detect_protocol_type(all_slots, contracts_before)
        self.logger.info(f"Protocol type: {protocol_info['type'].value} (confidence: {protocol_info['confidence']:.2f})")

        # Step 3: Find relationships (传入 diff 信息)
        step_num += 1
        self.logger.info(f"\n[{step_num}/{total_steps}] Detecting storage relationships...")
        relationships = self.relationship_detector.find_relationships(
            all_slots,
            protocol_info,
            contracts_before,
            storage_diffs=storage_diffs if storage_diffs else None
        )

        # Step 4: Generate invariants
        step_num += 1
        self.logger.info(f"\n[{step_num}/{total_steps}] Generating invariants...")
        invariants = self.invariant_generator.generate_invariants(relationships, protocol_info)

        self.logger.info("\n" + "="*80)
        self.logger.info(f"Analysis complete: {len(invariants)} storage invariants generated")
        if storage_diffs:
            self.logger.info(f"使用了基于攻击 diff 的动态阈值计算")
        self.logger.info("="*80)

        result = {
            'storage_slots': [asdict(s) for s in all_slots],
            'protocol_info': {
                'type': protocol_info['type'].value,
                'confidence': protocol_info['confidence'],
                'evidence': protocol_info['evidence'],
                'primary_contract': protocol_info.get('primary_contract'),
                'metadata': protocol_info.get('metadata', {})
            },
            'relationships': [asdict(r) for r in relationships],
            'invariants': [asdict(inv) for inv in invariants]
        }

        # 如果有 diff，添加到结果中
        if storage_diffs:
            result['storage_diffs'] = storage_diffs
            result['used_diff_analysis'] = True
        else:
            result['used_diff_analysis'] = False

        return result

    def _compute_storage_diffs(
        self,
        contracts_before: Dict[str, ContractState],
        contracts_after: Dict[str, ContractState]
    ) -> Dict[str, Dict[str, Any]]:
        """
        计算攻击前后的存储槽变化

        Args:
            contracts_before: 攻击前合约状态
            contracts_after: 攻击后合约状态

        Returns:
            {
                "0xAddress": {
                    "changed_slots": ["0x2", "0x5"],
                    "slot_diffs": {
                        "0x2": {
                            "before": "0x123",
                            "after": "0x456",
                            "before_int": 123,
                            "after_int": 456,
                            "change_rate": 0.5
                        }
                    }
                }
            }
        """
        diffs = {}

        for addr, before_contract in contracts_before.items():
            # 跳过不在 after 中的合约
            if addr not in contracts_after:
                continue

            after_contract = contracts_after[addr]

            changed_slots = []
            slot_diffs = {}

            # 对比每个槽位
            for slot, before_val in before_contract.storage.items():
                after_val = after_contract.storage.get(slot, "0x0")

                # 规范化值格式（确保都是 hex 字符串）
                if not before_val.startswith('0x'):
                    before_val = '0x' + before_val
                if not after_val.startswith('0x'):
                    after_val = '0x' + after_val

                # 检查是否变化
                if before_val != after_val:
                    changed_slots.append(slot)

                    # 尝试转换为整数计算变化率
                    try:
                        before_int = int(before_val, 16)
                        after_int = int(after_val, 16)

                        change_rate = 0.0
                        if before_int != 0:
                            change_rate = abs(after_int - before_int) / before_int
                        elif after_int != 0:
                            # before 为 0，after 非 0，认为是无穷大变化
                            change_rate = float('inf')

                        slot_diffs[slot] = {
                            "before": before_val,
                            "after": after_val,
                            "before_int": before_int,
                            "after_int": after_int,
                            "change_rate": change_rate,
                            "absolute_change": abs(after_int - before_int)
                        }

                    except (ValueError, OverflowError):
                        # 非数值槽位 (如地址、字节数据)
                        slot_diffs[slot] = {
                            "before": before_val,
                            "after": after_val,
                            "change_type": "non_numeric"
                        }

            # 只记录有变化的合约
            if changed_slots:
                diffs[addr] = {
                    "changed_slots": changed_slots,
                    "slot_diffs": slot_diffs,
                    "total_changes": len(changed_slots)
                }

                # 记录最大变化率（用于日志）
                numeric_changes = [
                    d['change_rate']
                    for d in slot_diffs.values()
                    if 'change_rate' in d and d['change_rate'] != float('inf')
                ]

                if numeric_changes:
                    max_change = max(numeric_changes)
                    diffs[addr]['max_change_rate'] = max_change
                    self.logger.debug(
                        f"  {addr[:10]}...: {len(changed_slots)} 槽变化, "
                        f"最大变化率 {max_change:.2%}"
                    )

        return diffs

