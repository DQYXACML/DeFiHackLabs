// SPDX-License-Identifier: MIT
pragma solidity 0.8.2;

import "./ReadWriteAccessControllerInterface.sol";

/**
 *  @notice Getters and setters for access controller
 */
interface ReadWriteAccessControlledInterface {
  event AccessControllerSet(address indexed accessController, address indexed sender);

  function setAccessController(ReadWriteAccessControllerInterface _accessController) external;

  function getAccessController() external view returns (ReadWriteAccessControllerInterface);
}
