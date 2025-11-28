"""
InvariantGeneratorV2 - 主控制器

整合所有分析模块,提供端到端的不变量生成工作流。
"""

import logging
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import asdict

from .storage_layout import SlotSemanticMapper, StorageLayoutCalculator, SlotSemanticType
from .protocol_detection import ProtocolDetectorV2, ProtocolType
from .state_analysis import StateDiffCalculator, ChangePatternDetector, ContractState
from .invariant_generation import ComplexInvariantGenerator, BusinessLogicTemplates

# 导入新的协议槽位解析器
# 获取项目根目录(FirewallOnchain/)
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent.parent.parent  # 从invariant_toolkit回到FirewallOnchain
utils_path = project_root / "scripts" / "tools" / "firewall_integration" / "utils"

if utils_path.exists() and str(utils_path) not in sys.path:
    sys.path.insert(0, str(utils_path))

try:
    from protocol_slot_resolver import ProtocolSlotResolver, ProtocolType as PSRProtocolType
    PROTOCOL_SLOT_RESOLVER_AVAILABLE = True
except ImportError as e:
    PROTOCOL_SLOT_RESOLVER_AVAILABLE = False
    logging.warning(f"协议槽位解析器不可用: {e}")

logger = logging.getLogger(__name__)


class InvariantGeneratorV2:
    """
    不变量生成器 V2.0

    端到端工作流:
    1. 加载合约数据 (ABI, 源码, attack_state)
    2. 检测协议类型
    3. 映射槽位语义
    4. 分析状态差异
    5. 检测攻击模式
    6. 生成复杂不变量
    7. 导出结果
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.InvariantGeneratorV2')

        # 初始化所有子模块
        self.protocol_detector = ProtocolDetectorV2()
        self.slot_mapper = SlotSemanticMapper()
        self.diff_calculator = StateDiffCalculator()
        self.pattern_detector = ChangePatternDetector()
        self.invariant_generator = ComplexInvariantGenerator()

        # 初始化协议槽位解析器(如果可用)
        if PROTOCOL_SLOT_RESOLVER_AVAILABLE:
            self.protocol_slot_resolver = ProtocolSlotResolver()
            self.logger.info("✓ 协议槽位解析器已启用")
        else:
            self.protocol_slot_resolver = None
            self.logger.warning("⚠ 协议槽位解析器不可用,使用基础映射")

        self.logger.info("InvariantGeneratorV2 初始化完成")

    def generate_from_project(
        self,
        project_dir: Path,
        output_path: Optional[Path] = None
    ) -> Dict:
        """
        从项目目录生成不变量

        Args:
            project_dir: 项目目录 (如 extracted_contracts/2024-01/BarleyFinance_exp)
            output_path: 输出路径 (默认为 project_dir/invariants_v2.json)

        Returns:
            生成结果字典
        """
        self.logger.info(f"开始处理项目: {project_dir}")

        project_dir = Path(project_dir)
        if not project_dir.exists():
            raise FileNotFoundError(f"项目目录不存在: {project_dir}")

        result = {
            "project": project_dir.name,
            "protocol_type": None,
            "invariants": [],
            "statistics": {},
            "errors": []
        }

        try:
            # 步骤1: 加载数据
            self.logger.info("步骤1: 加载项目数据...")
            data = self._load_project_data(project_dir)

            # 步骤2: 检测协议类型
            self.logger.info("步骤2: 检测协议类型...")
            protocol_result = self.protocol_detector.detect_with_confidence(
                contract_dir=data.get("main_contract_dir"),
                abi=data.get("abi"),
                project_name=project_dir.name
            )
            result["protocol_type"] = protocol_result.detected_type.value
            result["protocol_confidence"] = protocol_result.confidence

            # 将协议类型传入data,供后续步骤使用
            data["protocol_type"] = protocol_result.detected_type.value

            self.logger.info(
                f"  检测到协议类型: {protocol_result.detected_type.value} "
                f"(置信度: {protocol_result.confidence:.2%})"
            )

            # 步骤3: 映射槽位语义
            self.logger.info("步骤3: 映射槽位语义...")
            semantic_mapping = self._map_slot_semantics(data)
            result["semantic_mapping_coverage"] = self._calculate_coverage(semantic_mapping)

            # 步骤4: 分析状态差异
            diff_report = None
            patterns = []

            if data.get("has_diff_data"):
                # 新格式: 有before/after对比数据
                self.logger.info("步骤4: 分析状态差异 (before/after模式)...")
                diff_report = self._analyze_state_diff_from_files(
                    data["before_state"],
                    data["after_state"],
                    semantic_mapping
                )

                if diff_report:
                    result["state_changes"] = {
                        "contracts_changed": diff_report.total_contracts_changed,
                        "slots_changed": diff_report.total_slots_changed,
                        "extreme_changes": len(diff_report.extreme_changes)
                    }

                    # 步骤5: 检测攻击模式
                    self.logger.info("步骤5: 检测攻击模式...")
                    patterns = self.pattern_detector.detect_patterns(diff_report)
                    result["attack_patterns"] = [
                        {
                            "type": p.pattern_type.value,
                            "severity": p.severity,
                            "confidence": p.confidence,
                            "description": p.description
                        }
                        for p in patterns
                    ]

                    self.logger.info(f"  检测到 {len(patterns)} 个攻击模式")

            elif data.get("attack_state"):
                # 旧格式: 只有单点状态,降级模式
                self.logger.warning("步骤4-5: 跳过(无before/after数据,降级模式)")
                result["state_changes"] = {
                    "contracts_changed": 0,
                    "slots_changed": 0,
                    "extreme_changes": 0
                }
                result["attack_patterns"] = []

            # 步骤6: 生成不变量
            self.logger.info("步骤6: 生成复杂不变量...")
            invariants = self.invariant_generator.generate_invariants(
                protocol_type=protocol_result.detected_type,
                storage_layout=data.get("storage_layout", {}),
                diff_report=diff_report,
                patterns=patterns,
                semantic_mapping=semantic_mapping
            )

            result["invariants"] = [asdict(inv) for inv in invariants]
            result["statistics"]["total_invariants"] = len(invariants)
            result["statistics"]["by_category"] = self._count_by_category(invariants)
            result["statistics"]["by_severity"] = self._count_by_severity(invariants)

            self.logger.info(f"  生成了 {len(invariants)} 个不变量")

            # 步骤7: 导出结果
            if output_path is None:
                output_path = project_dir / "invariants_v2.json"

            self._export_results(result, output_path)
            self.logger.info(f"结果已导出到: {output_path}")

        except Exception as e:
            self.logger.error(f"处理过程中出错: {e}", exc_info=True)
            result["errors"].append(str(e))

        return result

    def _load_project_data(self, project_dir: Path) -> Dict:
        """
        加载项目数据

        支持两种数据格式:
        1. 新格式: attack_state.json(before) + attack_state_after.json(after)
        2. 旧格式: attack_state.json(单点状态)
        """
        data = {}

        # 查找主合约目录
        contract_dirs = [d for d in project_dir.iterdir() if d.is_dir() and d.name.startswith("0x")]
        if contract_dirs:
            data["main_contract_dir"] = contract_dirs[0]

            # 加载ABI
            abi_path = contract_dirs[0] / "abi.json"
            if abi_path.exists():
                with open(abi_path, 'r') as f:
                    data["abi"] = json.load(f)
                self.logger.debug(f"  加载ABI: {abi_path}")

        # 检查是否有before/after数据(新格式)
        before_path = project_dir / "attack_state.json"
        after_path = project_dir / "attack_state_after.json"

        if before_path.exists() and after_path.exists():
            # 新格式: 完整的before/after对比
            with open(before_path, 'r') as f:
                data["before_state"] = json.load(f)
            with open(after_path, 'r') as f:
                data["after_state"] = json.load(f)

            data["has_diff_data"] = True
            self.logger.info(f"  ✅ 检测到before/after数据格式")
            self.logger.debug(f"    before: {before_path}")
            self.logger.debug(f"    after: {after_path}")

        elif before_path.exists():
            # 旧格式: 只有单点状态,降级模式
            with open(before_path, 'r') as f:
                data["attack_state"] = json.load(f)

            data["has_diff_data"] = False
            self.logger.warning(f"  ⚠️  只有单点状态,部分功能受限")
            self.logger.debug(f"    single point: {before_path}")

        # 加载addresses.json
        addresses_path = project_dir / "addresses.json"
        if addresses_path.exists():
            with open(addresses_path, 'r') as f:
                data["addresses"] = json.load(f)
            self.logger.debug(f"  加载addresses: {addresses_path}")

        return data

    def _map_slot_semantics(self, data: Dict) -> Dict[str, Dict[str, str]]:
        """
        映射所有合约的槽位语义

        支持两种格式:
        1. 新格式: 从before_state获取
        2. 旧格式: 从attack_state获取

        改进: 如果启用了ProtocolSlotResolver,优先使用协议特定的槽位映射
        """
        semantic_mapping = {}

        # 优先使用before_state (新格式)
        state_source = None
        if "before_state" in data and "addresses" in data["before_state"]:
            state_source = data["before_state"]
        elif "attack_state" in data and "addresses" in data["attack_state"]:
            state_source = data["attack_state"]

        if not state_source:
            self.logger.warning("未找到状态数据,跳过槽位映射")
            return semantic_mapping

        # 如果有协议槽位解析器,尝试使用协议特定映射
        protocol_type_detected = data.get("protocol_type")

        for address, state in state_source["addresses"].items():
            if "storage" not in state:
                continue

            semantic_mapping[address] = {}

            # 尝试使用协议槽位解析器
            if self.protocol_slot_resolver and protocol_type_detected:
                protocol_mapping_used = self._apply_protocol_slot_mapping(
                    address,
                    state,
                    protocol_type_detected,
                    semantic_mapping
                )

                if protocol_mapping_used:
                    self.logger.debug(f"  ✓ 合约{address[:10]}...使用协议特定槽位映射({protocol_type_detected})")
                    continue

            # 降级到基础语义映射
            for slot, value in state["storage"].items():
                # 基于值推断语义
                result = self.slot_mapper.map_variable_to_semantic(
                    variable_name=f"slot_{slot}",
                    value=value
                )
                semantic_mapping[address][slot] = result["semantic_type"].value

        return semantic_mapping

    def _apply_protocol_slot_mapping(
        self,
        address: str,
        state: Dict,
        protocol_type_str: str,
        semantic_mapping: Dict
    ) -> bool:
        """
        应用协议特定的槽位映射

        Args:
            address: 合约地址
            state: 合约状态数据
            protocol_type_str: 协议类型字符串
            semantic_mapping: 语义映射字典(会被修改)

        Returns:
            是否成功应用协议映射
        """
        try:
            # 映射协议类型字符串到PSRProtocolType枚举
            protocol_type_mapping = {
                "uniswap_v2_pair": PSRProtocolType.UNISWAP_V2_PAIR,
                "uniswap_v3_pool": PSRProtocolType.UNISWAP_V3_POOL,
                "erc20": PSRProtocolType.ERC20_STANDARD,
                "lending_protocol": PSRProtocolType.LENDING_PROTOCOL,
            }

            psr_protocol_type = protocol_type_mapping.get(protocol_type_str.lower())
            if not psr_protocol_type:
                return False

            # 获取关键槽位
            critical_slots = self.protocol_slot_resolver.get_critical_slots(
                psr_protocol_type,
                min_severity="medium"  # 包含medium及以上的槽位
            )

            if not critical_slots:
                return False

            # 映射槽位到语义
            for slot_info in critical_slots:
                slot_num = str(slot_info["slot"])

                # 检查该槽位是否存在于状态中
                if slot_num in state["storage"]:
                    semantic_mapping[address][slot_num] = slot_info["semantic"]
                    self.logger.debug(f"    Slot {slot_num}: {slot_info['name']} ({slot_info['semantic']})")

            return len(critical_slots) > 0

        except Exception as e:
            self.logger.debug(f"  协议槽位映射失败: {e}")
            return False

    def _analyze_state_diff(
        self,
        attack_state: Dict,
        semantic_mapping: Dict[str, Dict[str, str]]
    ):
        """分析状态差异"""

        # 构建before和after状态
        before_states = {}
        after_states = {}

        if "addresses" in attack_state:
            for address, state_data in attack_state["addresses"].items():
                # 简化实现: 假设attack_state包含before/after快照
                # 实际实现需要根据具体数据格式调整

                before_states[address] = ContractState(
                    address=address,
                    storage=state_data.get("storage", {}),
                    balance=state_data.get("balance", "0x0"),
                    nonce=state_data.get("nonce", 0)
                )

                # 如果有after状态,使用它;否则使用相同状态(表示无变化)
                after_states[address] = ContractState(
                    address=address,
                    storage=state_data.get("storage", {}),
                    balance=state_data.get("balance", "0x0"),
                    nonce=state_data.get("nonce", 0)
                )

        return self.diff_calculator.compute_comprehensive_diff(
            before=before_states,
            after=after_states,
            semantic_mapping=semantic_mapping
        )

    def _analyze_state_diff_from_files(
        self,
        before_state: Dict,
        after_state: Dict,
        semantic_mapping: Dict[str, Dict[str, str]]
    ):
        """
        从before/after文件分析状态差异

        Args:
            before_state: attack_state.json的内容(before)
            after_state: attack_state_after.json的内容(after)
            semantic_mapping: 槽位语义映射

        Returns:
            DiffReport对象
        """
        before_states = {}
        after_states = {}

        # 构建before状态
        if "addresses" in before_state:
            for address, state_data in before_state["addresses"].items():
                before_states[address] = ContractState(
                    address=address,
                    storage=state_data.get("storage", {}),
                    balance=state_data.get("balance_wei", "0x0"),
                    nonce=state_data.get("nonce", 0)
                )

        # 构建after状态
        if "addresses" in after_state:
            for address, state_data in after_state["addresses"].items():
                after_states[address] = ContractState(
                    address=address,
                    storage=state_data.get("storage", {}),
                    balance=state_data.get("balance_wei", "0x0"),
                    nonce=state_data.get("nonce", 0)
                )

        # 计算差异
        return self.diff_calculator.compute_comprehensive_diff(
            before=before_states,
            after=after_states,
            semantic_mapping=semantic_mapping
        )

    def _calculate_coverage(self, semantic_mapping: Dict) -> float:
        """计算槽位语义映射覆盖率"""
        total_slots = 0
        mapped_slots = 0

        for contract_slots in semantic_mapping.values():
            total_slots += len(contract_slots)
            mapped_slots += sum(
                1 for semantic in contract_slots.values()
                if semantic != SlotSemanticType.UNKNOWN.value
            )

        return mapped_slots / total_slots if total_slots > 0 else 0.0

    def _count_by_category(self, invariants: List) -> Dict[str, int]:
        """按类别统计不变量"""
        counts = {}
        for inv in invariants:
            category = inv.category
            counts[category] = counts.get(category, 0) + 1
        return counts

    def _count_by_severity(self, invariants: List) -> Dict[str, int]:
        """按严重性统计不变量"""
        counts = {}
        for inv in invariants:
            severity = inv.severity
            counts[severity] = counts.get(severity, 0) + 1
        return counts

    def _export_results(self, result: Dict, output_path: Path):
        """导出结果到JSON"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    def batch_generate(
        self,
        base_dir: Path,
        pattern: str = "2024-*",
        max_workers: int = 4
    ) -> Dict[str, Dict]:
        """
        批量生成不变量

        Args:
            base_dir: 基础目录 (如 extracted_contracts)
            pattern: 目录匹配模式
            max_workers: 最大并行数

        Returns:
            {project_name: result}
        """
        import glob
        from concurrent.futures import ThreadPoolExecutor, as_completed

        self.logger.info(f"开始批量处理: {base_dir}/{pattern}")

        # 查找所有匹配的项目
        search_path = base_dir / pattern
        project_dirs = [Path(p) for p in glob.glob(str(search_path)) if Path(p).is_dir()]

        self.logger.info(f"找到 {len(project_dirs)} 个项目")

        results = {}

        # 并行处理
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_project = {
                executor.submit(self.generate_from_project, proj_dir): proj_dir
                for proj_dir in project_dirs
            }

            for future in as_completed(future_to_project):
                proj_dir = future_to_project[future]
                try:
                    result = future.result()
                    results[proj_dir.name] = result
                    self.logger.info(f"✓ {proj_dir.name}: {result['statistics'].get('total_invariants', 0)} 个不变量")
                except Exception as e:
                    self.logger.error(f"✗ {proj_dir.name}: {e}")
                    results[proj_dir.name] = {"error": str(e)}

        # 生成汇总报告
        self._generate_summary_report(results, base_dir / "batch_summary_v2.json")

        return results

    def _generate_summary_report(self, results: Dict, output_path: Path):
        """生成批量处理汇总报告"""
        summary = {
            "total_projects": len(results),
            "successful": sum(1 for r in results.values() if "error" not in r),
            "failed": sum(1 for r in results.values() if "error" in r),
            "total_invariants": sum(
                r.get("statistics", {}).get("total_invariants", 0)
                for r in results.values()
                if "error" not in r
            ),
            "by_protocol": {},
            "details": results
        }

        # 按协议类型统计
        for proj_name, result in results.items():
            if "error" in result:
                continue

            protocol = result.get("protocol_type", "unknown")
            if protocol not in summary["by_protocol"]:
                summary["by_protocol"][protocol] = {
                    "count": 0,
                    "total_invariants": 0
                }

            summary["by_protocol"][protocol]["count"] += 1
            summary["by_protocol"][protocol]["total_invariants"] += result.get("statistics", {}).get("total_invariants", 0)

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        self.logger.info(f"汇总报告已保存: {output_path}")
