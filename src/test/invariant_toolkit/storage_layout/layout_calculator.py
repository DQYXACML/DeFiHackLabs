"""
存储布局计算器

根据Solidity存储规则计算状态变量的槽位布局。

支持:
- 基础类型的连续分配和packed storage
- Mapping和dynamic array的槽位计算
- Struct成员的槽位展开
- 继承链中的槽位继承
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from hashlib import sha3_256
import struct

logger = logging.getLogger(__name__)


@dataclass
class StateVariable:
    """状态变量定义"""
    name: str
    var_type: str
    visibility: str = "internal"  # public, private, internal
    constant: bool = False
    immutable: bool = False
    offset: int = 0  # 在槽位中的字节偏移


@dataclass
class SlotInfo:
    """槽位信息"""
    slot: int
    offset: int  # 字节偏移 (0-31)
    size: int  # 字节大小
    type: str
    name: str
    is_mapping: bool = False
    is_array: bool = False
    mapping_key_type: Optional[str] = None
    array_element_type: Optional[str] = None


class StorageLayoutCalculator:
    """
    存储布局计算器

    实现Solidity存储布局规则:
    1. 状态变量按声明顺序分配槽位
    2. 小于32字节的变量尝试packed storage
    3. Mapping和dynamic array单独占用槽位
    4. Struct展开成员
    5. 继承的父合约变量优先分配
    """

    # 类型大小映射 (字节)
    TYPE_SIZES = {
        "bool": 1,
        "uint8": 1,
        "int8": 1,
        "uint16": 2,
        "int16": 2,
        "uint24": 3,
        "int24": 3,
        "uint32": 4,
        "int32": 4,
        "uint40": 5,
        "int40": 5,
        "uint48": 6,
        "int48": 6,
        "uint56": 7,
        "int56": 7,
        "uint64": 8,
        "int64": 8,
        "uint72": 9,
        "uint80": 10,
        "uint88": 11,
        "uint96": 12,
        "uint104": 13,
        "uint112": 14,
        "uint120": 15,
        "uint128": 16,
        "int128": 16,
        "uint136": 17,
        "uint144": 18,
        "uint152": 19,
        "uint160": 20,  # address
        "address": 20,
        "uint168": 21,
        "uint176": 22,
        "uint184": 23,
        "uint192": 24,
        "uint200": 25,
        "uint208": 26,
        "uint216": 27,
        "uint224": 28,
        "uint232": 29,
        "uint240": 30,
        "uint248": 31,
        "uint256": 32,
        "int256": 32,
        "bytes1": 1,
        "bytes2": 2,
        "bytes3": 3,
        "bytes4": 4,
        "bytes8": 8,
        "bytes16": 16,
        "bytes32": 32,
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__ + '.StorageLayoutCalculator')

    def calculate_layout(
        self,
        variables: List[StateVariable],
        start_slot: int = 0
    ) -> Dict[str, SlotInfo]:
        """
        计算存储布局

        Args:
            variables: 状态变量列表 (按声明顺序)
            start_slot: 起始槽位 (用于继承)

        Returns:
            变量名 -> SlotInfo 的映射
        """
        layout = {}
        current_slot = start_slot
        current_offset = 0  # 当前槽位的偏移量

        for var in variables:
            # 跳过常量和immutable (不占用存储槽位)
            if var.constant or var.immutable:
                continue

            slot_info = self._calculate_variable_slot(
                var,
                current_slot,
                current_offset
            )

            layout[var.name] = slot_info

            # 更新下一个变量的位置
            if slot_info.is_mapping or slot_info.is_array:
                # Mapping和动态数组占用一个完整槽位
                current_slot += 1
                current_offset = 0
            else:
                # 尝试packed storage
                new_offset = current_offset + slot_info.size
                if new_offset > 32:
                    # 超过32字节,移到下一个槽位
                    current_slot += 1
                    current_offset = slot_info.size
                else:
                    current_offset = new_offset
                    # 如果正好32字节,移到下一个槽位
                    if current_offset == 32:
                        current_slot += 1
                        current_offset = 0

        self.logger.info(f"计算完成: {len(layout)} 个变量, 使用槽位 {start_slot}-{current_slot}")
        return layout

    def _calculate_variable_slot(
        self,
        var: StateVariable,
        current_slot: int,
        current_offset: int
    ) -> SlotInfo:
        """计算单个变量的槽位"""
        var_type = var.var_type.strip()

        # 1. 检查是否是mapping
        if var_type.startswith("mapping("):
            key_type, value_type = self._parse_mapping_type(var_type)
            return SlotInfo(
                slot=current_slot,
                offset=0,
                size=32,
                type=var_type,
                name=var.name,
                is_mapping=True,
                mapping_key_type=key_type
            )

        # 2. 检查是否是dynamic array
        if var_type.endswith("[]"):
            element_type = var_type[:-2].strip()
            return SlotInfo(
                slot=current_slot,
                offset=0,
                size=32,
                type=var_type,
                name=var.name,
                is_array=True,
                array_element_type=element_type
            )

        # 3. 基础类型
        size = self._get_type_size(var_type)

        return SlotInfo(
            slot=current_slot,
            offset=current_offset,
            size=size,
            type=var_type,
            name=var.name
        )

    def _get_type_size(self, var_type: str) -> int:
        """获取类型大小"""
        # 移除 array 标记
        base_type = var_type.split('[')[0].strip()

        # 查找精确匹配
        if base_type in self.TYPE_SIZES:
            return self.TYPE_SIZES[base_type]

        # 动态bytes和string占32字节
        if base_type in ["bytes", "string"]:
            return 32

        # Enum类型根据成员数量确定大小(默认uint8)
        if base_type.startswith("enum "):
            return 1

        # Struct类型(需要递归计算,这里简化为32)
        if base_type.startswith("struct "):
            return 32

        # 自定义类型默认32字节
        self.logger.warning(f"未知类型 {var_type}, 默认使用32字节")
        return 32

    def _parse_mapping_type(self, mapping_type: str) -> Tuple[str, str]:
        """解析mapping类型"""
        # mapping(address => uint256) -> ("address", "uint256")
        inner = mapping_type[8:-1]  # 去掉 "mapping(" 和 ")"
        parts = inner.split("=>")
        if len(parts) == 2:
            key_type = parts[0].strip()
            value_type = parts[1].strip()
            return key_type, value_type
        return "unknown", "unknown"

    def calculate_mapping_slot(
        self,
        key: str,
        base_slot: int,
        key_type: str = "address"
    ) -> int:
        """
        计算mapping派生槽位

        Solidity规则: keccak256(h(k) . p)
        其中:
        - k: mapping的key
        - p: mapping变量的槽位
        - h(): 编码函数 (对于elementary types就是padding)
        - .: 连接操作

        Args:
            key: mapping的key (如地址 "0x123...")
            base_slot: mapping变量的槽位
            key_type: key的类型 (默认address)

        Returns:
            派生槽位号 (十进制整数)
        """
        # 1. 编码key
        if key_type == "address":
            # Address左padding到32字节
            key_bytes = bytes.fromhex(key[2:].zfill(64))
        elif key_type in ["uint256", "int256"]:
            # uint256直接转bytes
            key_int = int(key, 16) if key.startswith("0x") else int(key)
            key_bytes = key_int.to_bytes(32, byteorder='big')
        else:
            # 其他类型简化处理
            key_bytes = bytes.fromhex(key[2:].zfill(64) if key.startswith("0x") else key.zfill(64))

        # 2. 编码槽位
        slot_bytes = base_slot.to_bytes(32, byteorder='big')

        # 3. 连接并计算keccak256
        concatenated = key_bytes + slot_bytes
        hash_bytes = sha3_256(concatenated).digest()

        # 4. 转换为整数
        slot_int = int.from_bytes(hash_bytes, byteorder='big')

        self.logger.debug(f"Mapping slot计算: key={key[:10]}..., base_slot={base_slot} -> {slot_int}")
        return slot_int

    def calculate_array_element_slot(
        self,
        index: int,
        base_slot: int
    ) -> int:
        """
        计算dynamic array元素槽位

        Solidity规则:
        - Array长度存储在base_slot
        - 元素从keccak256(base_slot) + index开始

        Args:
            index: 数组索引
            base_slot: 数组变量的槽位

        Returns:
            元素槽位号
        """
        # 1. 计算数组数据起始槽位
        slot_bytes = base_slot.to_bytes(32, byteorder='big')
        hash_bytes = sha3_256(slot_bytes).digest()
        data_slot = int.from_bytes(hash_bytes, byteorder='big')

        # 2. 加上索引
        element_slot = data_slot + index

        self.logger.debug(f"Array slot计算: index={index}, base_slot={base_slot} -> {element_slot}")
        return element_slot
