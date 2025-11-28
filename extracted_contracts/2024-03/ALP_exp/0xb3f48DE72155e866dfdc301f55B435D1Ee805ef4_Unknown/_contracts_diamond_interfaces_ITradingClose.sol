// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "./ITrading.sol";

struct CloseInfo {
    uint64 closePrice;  // 1e8
    int96 fundingFee;   // tokenIn decimals
    uint96 closeFee;    // tokenIn decimals
    int96 pnl;          // tokenIn decimals
    uint96 holdingFee;  // tokenIn decimals
}

interface ITradingClose is ITrading {

    event CloseTradeSuccessful(address indexed user, bytes32 indexed tradeHash, CloseInfo closeInfo);
    event ExecuteCloseSuccessful(address indexed user, bytes32 indexed tradeHash, ExecutionType executionType, CloseInfo closeInfo);
    event CloseTradeReceived(address indexed user, bytes32 indexed tradeHash, address indexed token, uint256 amount);
    event CloseTradeAddLiquidity(address indexed token, uint256 amount);
    event ExecuteCloseRejected(address indexed user, bytes32 indexed tradeHash, ExecutionType executionType, uint64 execPrice, uint64 marketPrice);

    enum ExecutionType {TP, SL, LIQ}
    struct TpSlOrLiq {
        bytes32 tradeHash;
        uint64 price;
        ExecutionType executionType;
    }

    struct SettleToken {
        address token;
        uint256 amount;
        uint8 decimals;
    }

    function closeTradeCallback(bytes32 tradeHash, uint upperPrice, uint lowerPrice) external;

    function executeTpSlOrLiq(TpSlOrLiq[] memory) external;
}
