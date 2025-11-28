"""
存储布局分析模块

提供Solidity合约存储槽位分析能力:
- 解析合约状态变量声明
- 计算存储槽位布局
- 识别槽位语义类型
"""

from .solidity_parser import SolidityParser
from .layout_calculator import StorageLayoutCalculator, StateVariable, SlotInfo
from .slot_semantic_mapper import SlotSemanticMapper, SlotSemanticType

__all__ = [
    "SolidityParser",
    "StorageLayoutCalculator",
    "StateVariable",
    "SlotInfo",
    "SlotSemanticMapper",
    "SlotSemanticType",
]
