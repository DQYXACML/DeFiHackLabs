// SPDX-License-Identifier: MIT
pragma solidity 0.8.2;

import "./access/OwnerIsCreator.sol";
import "./interfaces/DenominationsInterface.sol";
import "./library/EnumerableTradingPairMap.sol";

/**
 * @notice Provides functionality for maintaining trading pairs
 * @author Sri Krishna mannem
 */
contract Denominations is OwnerIsCreator, DenominationsInterface {
  using EnumerableTradingPairMap for EnumerableTradingPairMap.EnumerableMap;
  EnumerableTradingPairMap.EnumerableMap private m;

  /**
   * @notice insert a key.
   * @dev duplicate keys are not permitted.
   * @param base base asset string to insert
   * @param quote quote asset string to insert
   * @param baseAssetAddress canonical address of base asset
   * @param quoteAssetAddress canonical address of quote asset
   * @param feedAdapterAddress Address of Feed Adapter contract for this pair
   */
  function insertPair(
    string calldata base,
    string calldata quote,
    address baseAssetAddress,
    address quoteAssetAddress,
    address feedAdapterAddress
  ) external override onlyOwner {
    require(
      baseAssetAddress != address(0) && quoteAssetAddress != address(0) && feedAdapterAddress != address(0),
      "Addresses should not be null"
    );
    EnumerableTradingPairMap.TradingPairDetails memory value = EnumerableTradingPairMap.TradingPairDetails(
      baseAssetAddress,
      quoteAssetAddress,
      feedAdapterAddress
    );
    EnumerableTradingPairMap.insert(m, base, quote, value);
  }

  /**
   * @notice remove a key
   * @dev key to remove must exist.
   * @param base base asset to remove
   * @param quote quote asset to remove
   */
  function removePair(string calldata base, string calldata quote) external override onlyOwner {
    EnumerableTradingPairMap.remove(m, base, quote);
  }

  /**
   * @notice Retrieve details of a trading pair
   * @param base base asset string
   * @param quote quote asset string
   */
  function getTradingPairDetails(string calldata base, string calldata quote)
    external
    view
    override
    returns (
      address,
      address,
      address
    )
  {
    EnumerableTradingPairMap.TradingPairDetails memory details = EnumerableTradingPairMap.getTradingPair(
      m,
      base,
      quote
    );
    return (details.baseAssetAddress, details.quoteAssetAddress, details.feedAddress);
  }

  /**
   * @notice Total number of pairs available to query through FeedRegister
   */
  function totalPairsAvailable() external view override returns (uint256) {
    return EnumerableTradingPairMap.count(m);
  }

  /**
   * @notice Retrieve all pairs available to query though FeedRegister. Each pair is (base, quote)
   */
  function getAllPairs() external view override returns (EnumerableTradingPairMap.Pair[] memory) {
    return EnumerableTradingPairMap.getAllPairs(m);
  }

  /**
   * @notice Retrieve only base and quote addresses
   * @param base  base asset string
   * @param quote quote asset string
   * @return base asset address
   * @return quote asset address
   */
  function getTradingPairAddresses(string memory base, string memory quote) external view returns (address, address) {
    EnumerableTradingPairMap.TradingPairDetails memory details = EnumerableTradingPairMap.getTradingPair(
      m,
      base,
      quote
    );
    return (details.baseAssetAddress, details.quoteAssetAddress);
  }

  /**
   * @param base base asset string
   * @param quote quote asset string
   * @return bool true if a pair exists
   */
  function exists(string calldata base, string calldata quote) external view override returns (bool) {
    return EnumerableTradingPairMap.exists(m, base, quote);
  }
}
