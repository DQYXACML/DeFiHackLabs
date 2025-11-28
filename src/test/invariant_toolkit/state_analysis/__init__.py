"""
状态分析模块

提供攻击前后状态差异分析能力:
- 计算存储槽位变化
- 识别变化模式
- 构建因果关系图
"""

from .diff_calculator import StateDiffCalculator, ContractState, DiffReport
from .pattern_detector import ChangePatternDetector, ChangePattern
from .causality_graph import CausalityGraphBuilder

__all__ = [
    "StateDiffCalculator",
    "ContractState",
    "DiffReport",
    "ChangePatternDetector",
    "ChangePattern",
    "CausalityGraphBuilder",
]
