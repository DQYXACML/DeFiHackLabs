// SPDX-License-Identifier: UNLICENSED
pragma solidity 0.8.20;

import {FixedPointMathLib} from "solmate/utils/FixedPointMathLib.sol";
import {SafeCast} from "./libraries/SafeCast.sol";
import {LiquidityProviderBase} from "./LiquidityProviderBase.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts-upgradeable/proxy/utils/UUPSUpgradeable.sol";
import {ERC20Upgradeable} from "@openzeppelin/contracts-upgradeable/token/ERC20/ERC20Upgradeable.sol";

/// @notice Tokenized Uniswap V3 LP wrapper.
/// @custom:oz-upgrades-from src/UniV3/UniV3WrapperOld.sol:UniV3WrapperOld
contract UniV3Wrapper is LiquidityProviderBase, ERC20Upgradeable, UUPSUpgradeable {
    using SafeCast for uint256;
    using FixedPointMathLib for uint256;

    // Storage gap.
    uint256[50] internal __gapWrapper;

    error InsufficientLiquidityMinted();

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    /// @notice Initializer.
    function __Wrapper_init(address uniV3Pool, int24 _tickLower, int24 _tickUpper) public initializer {
        _init(uniV3Pool, _tickLower, _tickUpper);
    }

    function _init(address uniV3Pool, int24 _tickLower, int24 _tickUpper) internal {
        __Base_init(uniV3Pool, _tickLower, _tickUpper);
        string memory symbol0 = token0.symbol();
        string memory symbol1 = token1.symbol();
        __ERC20_init(
            string.concat("Uniswap V3 ", symbol0, " ", symbol1, " LP"), string.concat(symbol0, "-", symbol1, " LP")
        );
    }

    /// @notice Calculates the token0 and token1 amounts belonging to the contract.
    function getAssets() public view returns (uint256 amount0, uint256 amount1) {
        return getAssetsBasedOnPrice(getCurrentPrice());
    }

    /// @notice Calculates the token0 and token1 amounts belonging to the contract. Based on a given price.
    /// @dev An option to pass an external price source means we don't have to rely on the pool's price which can be manipulated.
    function getAssetsBasedOnPrice(uint160 price) public view returns (uint256 amount0, uint256 amount1) {
        (amount0, amount1) = getAmountsForLiquidity(totalLiquidity, price);
        (uint256 fees0, uint256 fees1) = getUnclaimedFees();
        amount0 += fees0 + balance0;
        amount1 += fees1 + balance1;
    }

    /// @notice Implementation of the UUPS proxy authorization.
    function _authorizeUpgrade(address) internal override onlyOwner {}

    /// @notice Collect fees and reinvest them as liquidity.
    function compound() public stablePrice returns (uint256 amount0, uint256 amount1, uint128 liquidityAdded) {
        return _compound();
    }

    /// @notice Swap some assets and add liquidity to the pool.
    /// @dev Call mintMaxLiquidityPreview() to get the swap data.
    function zapIn(
        uint256 startingAmount0,
        uint256 startingAmount1,
        uint256 swapAmount,
        bool zeroForOne,
        uint256 minAmount0Added,
        uint256 minAmount1Added
    ) external returns (uint256 swapAmountOut, uint128 liquidityMinted, uint256 sharesMinted) {
        _compound();
        swapAmountOut = _swap(zeroForOne, swapAmount, 0, msg.sender, address(this));
        if (zeroForOne) {
            startingAmount0 -= swapAmount;
            startingAmount1 += swapAmountOut;
        } else {
            startingAmount0 += swapAmountOut;
            startingAmount1 -= swapAmount;
        }
        (liquidityMinted, sharesMinted) = _deposit(startingAmount0, startingAmount1, minAmount0Added, minAmount1Added);
    }

    /// @notice Add liquidity to the pool.
    function deposit(uint256 startingAmount0, uint256 startingAmount1, uint256 minAmount0Added, uint256 minAmount1Added)
        external
        returns (uint128 liquidityMinted, uint256 sharesMinted)
    {
        _compound();
        (liquidityMinted, sharesMinted) = _deposit(startingAmount0, startingAmount1, minAmount0Added, minAmount1Added);
    }

    /// @notice Deposits liquidity into the pool and mints shares.
    /// @dev Call compound before calling this function.
    function _deposit(uint256 amount0, uint256 amount1, uint256 minAdded0, uint256 minAdded1)
        internal
        returns (uint128 liquidityAdded, uint256 sharesMinted)
    {
        (liquidityAdded,,) = mintLiquidityPreview(amount0, amount1);
        sharesMinted = totalLiquidity == 0
            ? liquidityAdded
            : uint256(liquidityAdded).mulDivDown(totalSupply(), uint256(totalLiquidity));
        (amount0, amount1) = _addLiquidity(liquidityAdded, msg.sender);
        _mint(msg.sender, sharesMinted);
        if (amount0 < minAdded0 || amount1 < minAdded1) {
            revert InsufficientLiquidityMinted();
        }
    }

    /// @notice Remove the proportional amount of liquidity from the pool and withdraw to the caller.
    function withdraw(uint256 shares) external returns (uint128 liquidityRemoved, uint256 amount0, uint256 amount1) {
        _compound();
        liquidityRemoved = uint128(shares.mulDivDown(totalLiquidity, totalSupply()));
        _burn(msg.sender, shares);
        (amount0, amount1) = _removeLiquidity(liquidityRemoved, msg.sender);
    }
}
