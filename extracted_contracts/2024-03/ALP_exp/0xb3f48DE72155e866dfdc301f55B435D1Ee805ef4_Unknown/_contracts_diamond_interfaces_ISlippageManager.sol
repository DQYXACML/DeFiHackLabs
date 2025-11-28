// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "./IPairsManager.sol";
import "../libraries/LibPairsManager.sol";

enum SlippageType{FIXED, ONE_PERCENT_DEPTH, NET_POSITION, THRESHOLD}

struct SlippageConfigView {
    uint256 onePercentDepthAboveUsd;
    uint256 onePercentDepthBelowUsd;
    uint16 slippageLongP;       // 1e4
    uint16 slippageShortP;      // 1e4
    uint256 longThresholdUsd;
    uint256 shortThresholdUsd;
    SlippageType slippageType;
}

interface ISlippageManager {

    event AddSlippageConfig(
        uint16 indexed index, SlippageType indexed slippageType,
        uint256 onePercentDepthAboveUsd, uint256 onePercentDepthBelowUsd,
        uint16 slippageLongP, uint16 slippageShortP,
        uint256 longThresholdUsd, uint256 shortThresholdUsd, string name
    );
    event RemoveSlippageConfig(uint16 indexed index);
    event UpdateSlippageConfig(
        uint16 indexed index, SlippageType indexed slippageType,
        uint256 onePercentDepthAboveUsd, uint256 onePercentDepthBelowUsd,
        uint16 slippageLongP, uint16 slippageShortP,
        uint256 longThresholdUsd, uint256 shortThresholdUsd
    );

    struct UpdateSlippageConfigParam {
        uint16 index;
        SlippageType slippageType;
        uint256 onePercentDepthAboveUsd;
        uint256 onePercentDepthBelowUsd;
        uint16 slippageLongP;    // 1e4
        uint16 slippageShortP;   // 1e4
        uint256 longThresholdUsd;
        uint256 shortThresholdUsd;
    }

    function addSlippageConfig(
        string calldata name, uint16 index, SlippageConfigView calldata sc
    ) external;

    function removeSlippageConfig(uint16 index) external;

    function updateSlippageConfig(UpdateSlippageConfigParam calldata param) external;

    function batchUpdateSlippageConfig(UpdateSlippageConfigParam[] calldata params) external;

    function getSlippageConfigByIndex(uint16 index) external view returns (LibPairsManager.SlippageConfig memory, IPairsManager.PairSimple[] memory);
}
