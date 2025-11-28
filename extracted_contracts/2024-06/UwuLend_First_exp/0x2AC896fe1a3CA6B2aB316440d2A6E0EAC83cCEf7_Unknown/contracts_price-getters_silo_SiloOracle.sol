// SPDX-License-Identifier: agpl-3.0
pragma solidity 0.6.6;

import {FullMath} from '../uniswap-v2/libraries/FullMath.sol';
import {IPriceGetter} from '../uniswap-v2/interfaces/IPriceGetter.sol';
import {IERC20Metadata} from '../uniswap-v2/interfaces/IERC20Metadata.sol';

import {IPriceProvider} from './interfaces/IPriceProvider.sol';

interface ICLAggregator {
  function decimals() external view returns (uint8);

  function latestAnswer() external view returns (int256);

  function latestTimestamp() external view returns (uint256);

  function latestRound() external view returns (uint256);

  function getAnswer(uint256 roundId) external view returns (int256);

  function getTimestamp(uint256 roundId) external view returns (uint256);

  event AnswerUpdated(int256 indexed current, uint256 indexed roundId, uint256 timestamp);
  event NewRound(uint256 indexed roundId, address indexed startedBy);
}

contract SiloOracle is IPriceGetter {
  ICLAggregator public immutable aggregator;
  IERC20Metadata public immutable token;
  IPriceProvider public immutable siloPriceProvider;

  constructor(
    IERC20Metadata _token,
    IPriceProvider _siloPriceProvider,
    ICLAggregator _aggregator
  ) public {
    token = _token;
    siloPriceProvider = _siloPriceProvider;
    aggregator = _aggregator;
  }

  function getPrice() external view override returns (uint256) {
    int256 cPrice = ICLAggregator(aggregator).latestAnswer();
    uint256 sPrice = siloPriceProvider.getPrice(address(token));
    uint8 decimals = token.decimals();

    return FullMath.mulDiv(uint256(cPrice), sPrice, 10 ** uint256(decimals));
  }
}
