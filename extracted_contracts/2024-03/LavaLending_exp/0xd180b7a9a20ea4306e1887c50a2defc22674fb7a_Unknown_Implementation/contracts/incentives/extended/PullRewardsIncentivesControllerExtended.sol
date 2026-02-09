// SPDX-License-Identifier: agpl-3.0
pragma solidity 0.7.5;
pragma experimental ABIEncoderV2;

import {IERC20} from '@aave/aave-stake/contracts/interfaces/IERC20.sol';
import {SafeERC20} from '@aave/aave-stake/contracts/lib/SafeERC20.sol';
import {BaseIncentivesControllerExtended} from './BaseIncentivesControllerExtended.sol';

/**
 * @title PullRewardsIncentivesController
 * @notice Distributor contract for ERC20 rewards to the Aave protocol participants that pulls ERC20 from external account
 * @author Aave
 **/
contract PullRewardsIncentivesControllerExtended is
  BaseIncentivesControllerExtended
{
  using SafeERC20 for IERC20;

  address internal _rewardsVault;

  mapping(address => uint256) public extendedRewardIndex;

  event RewardsVaultUpdated(address indexed vault);
  
  constructor(IERC20 rewardToken, address emissionManager)
    BaseIncentivesControllerExtended(rewardToken, emissionManager)
  {}

  /**
   * @dev Initialize AaveIncentivesController
   * @param rewardsVault rewards vault to pull ERC20 funds
   **/
  function initialize(address rewardsVault) external initializer {
    _rewardsVault = rewardsVault;
    emit RewardsVaultUpdated(_rewardsVault);
  }

  /**
   * @dev returns the current rewards vault contract
   * @return address
   */
  function getRewardsVault() external view returns (address) {
    return _rewardsVault;
  }

  /**
   * @dev update the rewards vault address, only allowed by the Rewards admin
   * @param rewardsVault The address of the rewards vault
   **/
  function setRewardsVault(address rewardsVault) external onlyEmissionManager {
    _rewardsVault = rewardsVault;
    emit RewardsVaultUpdated(rewardsVault);
  }

  function _transferRewards(address to, uint256 amount) internal override {
    IERC20(REWARD_TOKEN).safeTransferFrom(_rewardsVault, to, amount);
  }

  function _readAssetIndex(address asset) internal override view returns (uint256 index) {
    index = extendedRewardIndex[asset];
    if (index == 0) {
      index = assets[asset].index;
    }
  }

  function _setAssetIndex(address asset, uint256 index) internal override {
    extendedRewardIndex[asset] = index;
  }

}