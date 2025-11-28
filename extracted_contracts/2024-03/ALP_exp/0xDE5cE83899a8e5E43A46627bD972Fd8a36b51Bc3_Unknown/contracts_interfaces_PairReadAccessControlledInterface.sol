// SPDX-License-Identifier: MIT
pragma solidity 0.8.2;

import "./PairReadAccessControllerInterface.sol";

/**
 *  @notice Getters and setters for access controller
 */
interface PairReadAccessControlledInterface {
  event PairAccessControllerSet(address indexed accessController, address indexed sender);

  function setAccessController(PairReadAccessControllerInterface _accessController) external;

  function getAccessController() external view returns (PairReadAccessControllerInterface);
}
