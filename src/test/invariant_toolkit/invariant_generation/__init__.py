"""
复杂不变量生成模块

基于协议类型、状态差异和模式检测结果,
生成跨合约、多变量的业务逻辑不变量。
"""

from .complex_formula_builder import ComplexInvariantGenerator, ComplexInvariant
from .cross_contract_analyzer import CrossContractAnalyzer
from .business_logic_templates import BusinessLogicTemplates, InvariantCategory

__all__ = [
    "ComplexInvariantGenerator",
    "ComplexInvariant",
    "CrossContractAnalyzer",
    "BusinessLogicTemplates",
    "InvariantCategory",
]
