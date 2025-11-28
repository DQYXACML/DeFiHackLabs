// SPDX-License-Identifier: MIT
pragma solidity 0.8.2;

import "./access/OwnerIsCreator.sol";
import "./interfaces/FeedRegistryInterface.sol";
import "./interfaces/FeedAdapterInterface.sol";
import "./access/PairReadAccessControlled.sol";

/**
 * @title Feed Adapter which conforms to ChainLink's AggregatorV2V3Interface
 * @dev Calls Feed Register to route the request
 * @author Sri Krishna Mannem
 */
contract FeedAdapter is FeedAdapterInterface, PairReadAccessControlled {
  /// @notice canonical addresses of assets and feed name
  address public immutable BASE;
  address public immutable QUOTE;
  string internal FEED_PAIR_NAME;

  /// @dev FeedRegistry to route requests to
  FeedRegistryInterface private feedRegistry;

  /// @dev answers are stored in fixed-point format, with this many digits of precision
  uint8 public immutable override decimals;

  /// @notice aggregator contract version
  uint256 public constant override version = 6;

  constructor(
    FeedRegistryInterface feedRegistry_,
    address base_,
    address quote_,
    string memory feedPair_
  ) {
    require(base_ != address(0) && quote_ != address(0));
    feedRegistry = feedRegistry_;
    BASE = base_;
    QUOTE = quote_;
    FEED_PAIR_NAME = feedPair_;
    decimals = feedRegistry_.decimals(base_, quote_);
  }

  /**
   * @dev reverts if the caller does not have read access granted by the accessController contract
   */
  modifier checkReadAccess() {
    require(
      address(s_accessController) == address(0) ||
        s_accessController.hasGlobalAccess(msg.sender) ||
        s_accessController.hasPairAccess(msg.sender, BASE, QUOTE),
      "No read access"
    );
    _;
  }

  /***************************************************************************
   * Section: v2 AggregatorInterface
   **************************************************************************/
  /**
   * @notice median from the most recent report
   */
  function latestAnswer() external view virtual override checkReadAccess returns (int256) {
    return feedRegistry.latestAnswer(BASE, QUOTE);
  }

  /**
   * @notice timestamp of block in which last report was transmitted
   */
  function latestTimestamp() external view virtual override checkReadAccess returns (uint256) {
    return feedRegistry.latestTimestamp(BASE, QUOTE);
  }

  /**
   * @notice Aggregator round (NOT OCR round) in which last report was transmitted
   */
  function latestRound() external view virtual override checkReadAccess returns (uint256) {
    return feedRegistry.latestRound(BASE, QUOTE);
  }

  /**
   * @notice median of report from given aggregator round (NOT OCR round)
   * @param roundId the aggregator round of the target report
   */
  function getAnswer(uint256 roundId) external view virtual override checkReadAccess returns (int256) {
    return feedRegistry.getAnswer(BASE, QUOTE, roundId);
  }

  /**
   * @notice timestamp of block in which report from given aggregator round was transmitted
   * @param roundId aggregator round (NOT OCR round) of target report
   */
  function getTimestamp(uint256 roundId) external view virtual override checkReadAccess returns (uint256) {
    return feedRegistry.getTimestamp(BASE, QUOTE, roundId);
  }

  /***************************************************************************
   * Section: v3 AggregatorInterface
   **************************************************************************/

  /**
   * @notice human-readable description of observable this contract is reporting on
   */
  function description() external view virtual override returns (string memory) {
    return feedRegistry.description(BASE, QUOTE);
  }

  /**
   * @notice details for the given aggregator round
   * @param roundId target aggregator round (NOT OCR round). Must fit in uint32
   * @return roundId_ roundId
   * @return answer price of the pair at this round
   * @return startedAt timestamp of when observations were made offchain
   * @return updatedAt timestamp of block in which report from given roundId was transmitted
   * @return answeredInRound roundId
   */
  function getRoundData(uint80 roundId)
    external
    view
    virtual
    override
    checkReadAccess
    returns (
      uint80 roundId_,
      int256 answer,
      uint256 startedAt,
      uint256 updatedAt,
      uint80 answeredInRound
    )
  {
    return feedRegistry.getRoundData(BASE, QUOTE, roundId);
  }

  /**
   * @notice aggregator details for the most recently transmitted report
   * @return roundId aggregator round of latest report (NOT OCR round)
   * @return answer price of the pair at this round
   * @return startedAt timestamp of when observations were made offchain
   * @return updatedAt timestamp of block containing latest report
   * @return answeredInRound aggregator round of latest report
   */
  function latestRoundData()
    external
    view
    virtual
    override
    checkReadAccess
    returns (
      uint80 roundId,
      int256 answer,
      uint256 startedAt,
      uint256 updatedAt,
      uint80 answeredInRound
    )
  {
    return feedRegistry.latestRoundData(BASE, QUOTE);
  }
}
