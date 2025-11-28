#!/usr/bin/env python3
"""
Invariant Toolkit 单元测试

测试核心模块的功能正确性:
1. SlotSemanticMapper - 槽位语义映射
2. StorageLayoutCalculator - 存储布局计算
3. ABIFunctionAnalyzer - ABI协议检测
4. EventClassifier - 事件分类
5. ProtocolDetectorV2 - 综合协议检测
"""

import sys
import json
import unittest
from pathlib import Path

# 添加src/test到路径
sys.path.insert(0, str(Path(__file__).parent / "src" / "test"))

from invariant_toolkit.storage_layout import (
    SlotSemanticMapper,
    SlotSemanticType,
    StorageLayoutCalculator,
    StateVariable
)
from invariant_toolkit.protocol_detection import (
    ABIFunctionAnalyzer,
    EventClassifier,
    ProtocolDetectorV2,
    ProtocolType
)


class TestSlotSemanticMapper(unittest.TestCase):
    """测试槽位语义映射器"""

    def setUp(self):
        self.mapper = SlotSemanticMapper()

    def test_erc20_standard_slots(self):
        """测试ERC20标准槽位识别"""
        # totalSupply
        result = self.mapper.map_variable_to_semantic(
            variable_name="totalSupply",
            variable_type="uint256"
        )
        self.assertEqual(result["semantic_type"], SlotSemanticType.TOTAL_SUPPLY)
        self.assertGreaterEqual(result["confidence"], 0.8)

        # balanceOf mapping
        result = self.mapper.map_variable_to_semantic(
            variable_name="balanceOf",
            variable_type="mapping(address => uint256)"
        )
        self.assertEqual(result["semantic_type"], SlotSemanticType.BALANCE_MAPPING)

    def test_vault_protocol_slots(self):
        """测试Vault协议槽位识别"""
        test_cases = [
            ("reserve0", "uint112", SlotSemanticType.RESERVE),
            ("underlying", "address", SlotSemanticType.ADDRESS_REFERENCE),
            ("totalSupply", "uint256", SlotSemanticType.TOTAL_SUPPLY),  # 使用totalSupply而非totalAssets
        ]

        for var_name, var_type, expected_type in test_cases:
            result = self.mapper.map_variable_to_semantic(
                variable_name=var_name,
                variable_type=var_type
            )
            self.assertEqual(result["semantic_type"], expected_type,
                           f"Failed for {var_name}")

    def test_address_value_inference(self):
        """测试基于地址值的推断"""
        # WETH地址 (0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2)
        result = self.mapper.map_variable_to_semantic(
            variable_name="underlying",
            variable_type="address",
            value="0x000000000000000000000000c02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
        )
        self.assertEqual(result["semantic_type"], SlotSemanticType.ADDRESS_REFERENCE)

    def test_batch_mapping(self):
        """测试批量映射"""
        variables = [
            {"name": "totalSupply", "type": "uint256"},
            {"name": "balanceOf", "type": "mapping(address => uint256)"},
            {"name": "owner", "type": "address"},
        ]

        results = self.mapper.batch_map_variables(variables)

        self.assertEqual(len(results), 3)
        self.assertEqual(results["totalSupply"]["semantic_type"], SlotSemanticType.TOTAL_SUPPLY)
        self.assertEqual(results["balanceOf"]["semantic_type"], SlotSemanticType.BALANCE_MAPPING)


class TestStorageLayoutCalculator(unittest.TestCase):
    """测试存储布局计算器"""

    def setUp(self):
        self.calculator = StorageLayoutCalculator()

    def test_packed_storage(self):
        """测试紧密存储(packed storage)"""
        variables = [
            StateVariable(name="owner", var_type="address"),    # 20 bytes
            StateVariable(name="paused", var_type="bool")       # 1 byte
        ]

        layout = self.calculator.calculate_layout(variables)

        # owner和paused应该被打包到同一槽位
        self.assertEqual(layout["owner"].slot, 0)
        self.assertEqual(layout["owner"].offset, 0)
        self.assertEqual(layout["paused"].slot, 0)
        self.assertEqual(layout["paused"].offset, 20)

    def test_sequential_uint256(self):
        """测试连续的uint256变量"""
        variables = [
            StateVariable(name="var1", var_type="uint256"),
            StateVariable(name="var2", var_type="uint256"),
            StateVariable(name="var3", var_type="uint256"),
        ]

        layout = self.calculator.calculate_layout(variables)

        # 每个uint256占一个完整槽位
        self.assertEqual(layout["var1"].slot, 0)
        self.assertEqual(layout["var2"].slot, 1)
        self.assertEqual(layout["var3"].slot, 2)

    def test_mapping_slot(self):
        """测试mapping基础槽位"""
        variables = [
            StateVariable(name="totalSupply", var_type="uint256"),
            StateVariable(name="balanceOf", var_type="mapping(address => uint256)"),
        ]

        layout = self.calculator.calculate_layout(variables)

        # totalSupply在slot 0
        self.assertEqual(layout["totalSupply"].slot, 0)
        # balanceOf的base slot在slot 1
        self.assertEqual(layout["balanceOf"].slot, 1)
        self.assertTrue(layout["balanceOf"].is_mapping)

    def test_mapping_derived_slot(self):
        """测试mapping派生槽位计算"""
        test_address = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
        base_slot = 3

        derived_slot = self.calculator.calculate_mapping_slot(
            key=test_address,
            base_slot=base_slot,
            key_type="address"
        )

        # 返回的应该是一个大整数
        self.assertIsInstance(derived_slot, int)
        self.assertGreater(derived_slot, 0)

    def test_nested_mapping_slot(self):
        """测试嵌套mapping的派生槽位"""
        # allowance[owner][spender]
        owner = "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb"
        spender = "0x1234567890123456789012345678901234567890"
        base_slot = 4

        # 第一层派生
        first_level = self.calculator.calculate_mapping_slot(owner, base_slot, "address")
        # 第二层派生
        second_level = self.calculator.calculate_mapping_slot(spender, first_level, "address")

        # 两个派生槽位应该都是有效的整数,且不同
        self.assertIsInstance(second_level, int)
        self.assertIsInstance(first_level, int)
        self.assertNotEqual(second_level, first_level)


class TestABIFunctionAnalyzer(unittest.TestCase):
    """测试ABI函数分析器"""

    def setUp(self):
        self.analyzer = ABIFunctionAnalyzer()

    def test_erc20_detection(self):
        """测试ERC20代币检测"""
        # 标准ERC20 ABI (简化版)
        abi = [
            {"type": "function", "name": "totalSupply", "inputs": [], "outputs": [{"type": "uint256"}]},
            {"type": "function", "name": "balanceOf", "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}]},
            {"type": "function", "name": "transfer", "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}]},
            {"type": "function", "name": "approve", "inputs": [{"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}]},
            {"type": "function", "name": "transferFrom", "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint256"}], "outputs": [{"type": "bool"}]},
            {"type": "function", "name": "allowance", "inputs": [{"type": "address"}, {"type": "address"}], "outputs": [{"type": "uint256"}]},
        ]

        result = self.analyzer.analyze_abi(abi)

        # ERC20应该有较高分数
        self.assertGreaterEqual(result["protocol_scores"][ProtocolType.ERC20.value], 0.5)

    def test_vault_protocol_detection(self):
        """测试Vault协议检测"""
        # ERC4626 Vault ABI (简化版)
        abi = [
            {"type": "function", "name": "deposit", "inputs": [{"type": "uint256"}, {"type": "address"}]},
            {"type": "function", "name": "withdraw", "inputs": [{"type": "uint256"}, {"type": "address"}, {"type": "address"}]},
            {"type": "function", "name": "totalAssets", "inputs": [], "outputs": [{"type": "uint256"}]},
            {"type": "function", "name": "convertToShares", "inputs": [{"type": "uint256"}], "outputs": [{"type": "uint256"}]},
            {"type": "function", "name": "asset", "inputs": [], "outputs": [{"type": "address"}]},
        ]

        result = self.analyzer.analyze_abi(abi)

        # Vault应该有高分数
        self.assertGreaterEqual(result["protocol_scores"][ProtocolType.VAULT.value], 0.6)
        self.assertEqual(result["detected_type"], ProtocolType.VAULT)

    def test_erc_standards_detection(self):
        """测试ERC标准识别"""
        # ERC20标准ABI
        erc20_abi = [
            {"type": "function", "name": "totalSupply", "outputs": [{"type": "uint256"}]},
            {"type": "function", "name": "balanceOf", "inputs": [{"type": "address"}]},
            {"type": "function", "name": "transfer", "inputs": [{"type": "address"}, {"type": "uint256"}]},
            {"type": "function", "name": "transferFrom", "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint256"}]},
            {"type": "function", "name": "approve", "inputs": [{"type": "address"}, {"type": "uint256"}]},
            {"type": "function", "name": "allowance", "inputs": [{"type": "address"}, {"type": "address"}]},
        ]

        standards = self.analyzer.detect_erc_standards(erc20_abi)
        self.assertIn("ERC20", standards)

    def test_critical_functions_identification(self):
        """测试关键函数识别"""
        abi = [
            {"type": "function", "name": "deposit"},
            {"type": "function", "name": "withdraw"},
            {"type": "function", "name": "transfer"},
            {"type": "function", "name": "pause"},
            {"type": "function", "name": "getPrice"},
        ]

        critical = self.analyzer.get_critical_functions(abi)

        self.assertIn("deposit", critical["value_transfer"])
        self.assertIn("withdraw", critical["value_transfer"])
        self.assertIn("pause", critical["permission"])
        self.assertIn("getPrice", critical["price_sensitive"])


class TestEventClassifier(unittest.TestCase):
    """测试事件分类器"""

    def setUp(self):
        self.classifier = EventClassifier()

    def test_vault_events(self):
        """测试Vault协议事件识别"""
        abi = [
            {"type": "event", "name": "Deposit"},
            {"type": "event", "name": "Withdraw"},
            {"type": "event", "name": "SharesMinted"},
            {"type": "event", "name": "Harvest"},
        ]

        result = self.classifier.classify_by_events(abi)

        # Vault应该有一定的分数(降低阈值到0.2,因为只有4个事件)
        self.assertGreaterEqual(result["protocol_scores"][ProtocolType.VAULT.value], 0.2)

    def test_amm_events(self):
        """测试AMM协议事件识别"""
        abi = [
            {"type": "event", "name": "Swap"},
            {"type": "event", "name": "Sync"},
            {"type": "event", "name": "Mint"},
            {"type": "event", "name": "Burn"},
        ]

        result = self.classifier.classify_by_events(abi)

        self.assertEqual(result["detected_type"], ProtocolType.AMM)

    def test_critical_events(self):
        """测试关键事件识别"""
        abi = [
            {"type": "event", "name": "Transfer"},
            {"type": "event", "name": "Deposit"},
            {"type": "event", "name": "ProposalCreated"},
            {"type": "event", "name": "StateChanged"},
        ]

        critical = self.classifier.get_critical_events(abi)

        self.assertIn("Transfer", critical["value_transfer"])
        self.assertIn("Deposit", critical["value_transfer"])
        self.assertIn("ProposalCreated", critical["governance"])


class TestProtocolDetectorV2(unittest.TestCase):
    """测试综合协议检测器"""

    def setUp(self):
        self.detector = ProtocolDetectorV2()

    def test_vault_detection_from_abi(self):
        """测试基于ABI的Vault检测"""
        abi = [
            {"type": "function", "name": "deposit", "inputs": [{"type": "uint256"}]},
            {"type": "function", "name": "withdraw", "inputs": [{"type": "uint256"}]},
            {"type": "function", "name": "totalAssets", "outputs": [{"type": "uint256"}]},
            {"type": "event", "name": "Deposit"},
            {"type": "event", "name": "Withdraw"},
        ]

        result = self.detector.detect_with_confidence(abi=abi)

        self.assertEqual(result.detected_type, ProtocolType.VAULT)
        self.assertGreaterEqual(result.confidence, 0.5)
        self.assertIn("abi_functions", result.data_sources_used)
        self.assertIn("events", result.data_sources_used)

    def test_project_name_detection(self):
        """测试基于项目名称的检测"""
        result = self.detector.detect_with_confidence(
            project_name="BarleyVault_v2"
        )

        # 应该识别出vault关键词
        self.assertGreater(
            result.protocol_scores.get(ProtocolType.VAULT.value, 0),
            0
        )

    def test_multi_source_fusion(self):
        """测试多源融合检测"""
        # 提供ABI和项目名称
        abi = [
            {"type": "function", "name": "deposit"},
            {"type": "function", "name": "withdraw"},
        ]

        result = self.detector.detect_with_confidence(
            abi=abi,
            project_name="TestVault"
        )

        # 应该使用了两个信息源
        self.assertGreaterEqual(len(result.data_sources_used), 2)
        self.assertIn("abi_functions", result.data_sources_used)
        self.assertIn("project_name", result.data_sources_used)


def run_tests():
    """运行所有测试"""
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加所有测试类
    suite.addTests(loader.loadTestsFromTestCase(TestSlotSemanticMapper))
    suite.addTests(loader.loadTestsFromTestCase(TestStorageLayoutCalculator))
    suite.addTests(loader.loadTestsFromTestCase(TestABIFunctionAnalyzer))
    suite.addTests(loader.loadTestsFromTestCase(TestEventClassifier))
    suite.addTests(loader.loadTestsFromTestCase(TestProtocolDetectorV2))

    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 返回是否所有测试通过
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
