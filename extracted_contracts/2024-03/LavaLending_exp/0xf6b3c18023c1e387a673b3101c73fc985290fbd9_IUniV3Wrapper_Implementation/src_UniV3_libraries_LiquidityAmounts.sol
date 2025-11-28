// SPDX-License-Identifier: GPL-2.0-or-later

/* 
Adapted from https://github.com/Uniswap/v3-periphery/blob/main/contracts/libraries/LiquidityAmounts.sol

Changes:
    - getLiquidityForAmounts function now also returns the token amounts that do not attribute to liquidity.
Additions:
    - getEquivalentAmount function.
    - onesidedMintPreview function.
    - maxMintPreview function.
 */

pragma solidity >=0.5.0;

import "./FullMath.sol";
import "./Constants.sol";

/// @title Liquidity amount functions
/// @notice Provides functions for computing liquidity amounts from token amounts and prices
library LiquidityAmounts {
    /// @notice Downcasts uint256 to uint128
    /// @param x The uint258 to be downcasted
    /// @return y The passed value, downcasted to uint128
    function toUint128(uint256 x) private pure returns (uint128 y) {
        require((y = uint128(x)) == x);
    }

    /// @notice Computes the amount of liquidity received for a given amount of token0 and price range
    /// @dev Calculates amount0 * (sqrt(upper) * sqrt(lower)) / (sqrt(upper) - sqrt(lower))
    /// @param sqrtRatioAX96 A sqrt price representing the first tick boundary
    /// @param sqrtRatioBX96 A sqrt price representing the second tick boundary
    /// @param amount0 The amount0 being sent in
    /// @return liquidity The amount of returned liquidity
    function getLiquidityForAmount0(uint160 sqrtRatioAX96, uint160 sqrtRatioBX96, uint256 amount0)
        internal
        pure
        returns (uint128 liquidity)
    {
        if (sqrtRatioAX96 > sqrtRatioBX96) (sqrtRatioAX96, sqrtRatioBX96) = (sqrtRatioBX96, sqrtRatioAX96);
        uint256 intermediate = FullMath.mulDiv(sqrtRatioAX96, sqrtRatioBX96, Constants.Q96);
        return toUint128(FullMath.mulDiv(amount0, intermediate, sqrtRatioBX96 - sqrtRatioAX96));
    }

    /// @notice Computes the amount of liquidity received for a given amount of token1 and price range
    /// @dev Calculates amount1 / (sqrt(upper) - sqrt(lower)).
    /// @param sqrtRatioAX96 A sqrt price representing the first tick boundary
    /// @param sqrtRatioBX96 A sqrt price representing the second tick boundary
    /// @param amount1 The amount1 being sent in
    /// @return liquidity The amount of returned liquidity
    function getLiquidityForAmount1(uint160 sqrtRatioAX96, uint160 sqrtRatioBX96, uint256 amount1)
        internal
        pure
        returns (uint128 liquidity)
    {
        if (sqrtRatioAX96 > sqrtRatioBX96) (sqrtRatioAX96, sqrtRatioBX96) = (sqrtRatioBX96, sqrtRatioAX96);
        return toUint128(FullMath.mulDiv(amount1, Constants.Q96, sqrtRatioBX96 - sqrtRatioAX96));
    }

    /// @notice Computes the maximum amount of liquidity received for a given amount of token0, token1, the current
    /// pool prices and the prices at the tick boundaries
    /// @param sqrtRatioX96 A sqrt price representing the current pool prices
    /// @param sqrtRatioAX96 A sqrt price representing the first tick boundary
    /// @param sqrtRatioBX96 A sqrt price representing the second tick boundary
    /// @param amount0 The amount of token0 being sent in
    /// @param amount1 The amount of token1 being sent in
    /// @return liquidity The maximum amount of liquidity received
    /// @return token1Remains Whether token1 amount can be fully spent.
    function getLiquidityForAmounts(
        uint160 sqrtRatioX96,
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint256 amount0,
        uint256 amount1
    ) internal pure returns (uint128 liquidity, bool token1Remains, uint256 amountRemaining) {
        if (sqrtRatioAX96 > sqrtRatioBX96) (sqrtRatioAX96, sqrtRatioBX96) = (sqrtRatioBX96, sqrtRatioAX96);

        if (sqrtRatioX96 <= sqrtRatioAX96) {
            // We only add token0.
            liquidity = getLiquidityForAmount0(sqrtRatioAX96, sqrtRatioBX96, amount0);
            token1Remains = true;
            amountRemaining = amount1;
        } else if (sqrtRatioX96 < sqrtRatioBX96) {
            // We add both token0 and token1.
            uint128 liquidity0 = getLiquidityForAmount0(sqrtRatioX96, sqrtRatioBX96, amount0);
            uint128 liquidity1 = getLiquidityForAmount1(sqrtRatioAX96, sqrtRatioX96, amount1);
            // We can add liquidity0 on the left side of the range and liquidity1 on the right side.
            // The smaller of the two is the amount of liquidity that can be added across the whole range.
            // Calculate the token amount that is left over on the larger side.
            token1Remains = liquidity0 < liquidity1;
            liquidity = token1Remains ? liquidity0 : liquidity1;
            if (token1Remains) {
                amountRemaining = getAmount1ForLiquidity(sqrtRatioAX96, sqrtRatioX96, liquidity1 - liquidity0);
            } else {
                amountRemaining = getAmount0ForLiquidity(sqrtRatioX96, sqrtRatioBX96, liquidity0 - liquidity1);
            }
        } else {
            // We only add token1.
            liquidity = getLiquidityForAmount1(sqrtRatioAX96, sqrtRatioBX96, amount1);
            token1Remains = false;
            amountRemaining = amount0;
        }
    }

    /// @notice Computes the amount of token0 for a given amount of liquidity and a price range
    /// @param sqrtRatioAX96 A sqrt price representing the first tick boundary
    /// @param sqrtRatioBX96 A sqrt price representing the second tick boundary
    /// @param liquidity The liquidity being valued
    /// @return amount0 The amount of token0
    function getAmount0ForLiquidity(uint160 sqrtRatioAX96, uint160 sqrtRatioBX96, uint128 liquidity)
        internal
        pure
        returns (uint256 amount0)
    {
        if (sqrtRatioAX96 > sqrtRatioBX96) (sqrtRatioAX96, sqrtRatioBX96) = (sqrtRatioBX96, sqrtRatioAX96);

        return FullMath.mulDiv(uint256(liquidity) << Constants.RESOLUTION, sqrtRatioBX96 - sqrtRatioAX96, sqrtRatioBX96)
            / sqrtRatioAX96;
    }

    /// @notice Computes the amount of token1 for a given amount of liquidity and a price range
    /// @param sqrtRatioAX96 A sqrt price representing the first tick boundary
    /// @param sqrtRatioBX96 A sqrt price representing the second tick boundary
    /// @param liquidity The liquidity being valued
    /// @return amount1 The amount of token1
    function getAmount1ForLiquidity(uint160 sqrtRatioAX96, uint160 sqrtRatioBX96, uint128 liquidity)
        internal
        pure
        returns (uint256 amount1)
    {
        if (sqrtRatioAX96 > sqrtRatioBX96) (sqrtRatioAX96, sqrtRatioBX96) = (sqrtRatioBX96, sqrtRatioAX96);

        return FullMath.mulDiv(liquidity, sqrtRatioBX96 - sqrtRatioAX96, Constants.Q96);
    }

    /// @notice Computes the token0 and token1 value for a given amount of liquidity, the current
    /// pool prices and the prices at the tick boundaries
    /// @param sqrtRatioX96 A sqrt price representing the current pool prices
    /// @param sqrtRatioAX96 A sqrt price representing the first tick boundary
    /// @param sqrtRatioBX96 A sqrt price representing the second tick boundary
    /// @param liquidity The liquidity being valued
    /// @return amount0 The amount of token0
    /// @return amount1 The amount of token1
    function getAmountsForLiquidity(
        uint160 sqrtRatioX96,
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint128 liquidity
    ) internal pure returns (uint256 amount0, uint256 amount1) {
        if (sqrtRatioAX96 > sqrtRatioBX96) (sqrtRatioAX96, sqrtRatioBX96) = (sqrtRatioBX96, sqrtRatioAX96);

        if (sqrtRatioX96 <= sqrtRatioAX96) {
            amount0 = getAmount0ForLiquidity(sqrtRatioAX96, sqrtRatioBX96, liquidity);
        } else if (sqrtRatioX96 < sqrtRatioBX96) {
            amount0 = getAmount0ForLiquidity(sqrtRatioX96, sqrtRatioBX96, liquidity);
            amount1 = getAmount1ForLiquidity(sqrtRatioAX96, sqrtRatioX96, liquidity);
        } else {
            amount1 = getAmount1ForLiquidity(sqrtRatioAX96, sqrtRatioBX96, liquidity);
        }
    }

    // This assumes no price impact.
    function getEquivalentAmount(uint256 amountA, bool isToken0, uint160 sqrtRatioX96, uint128 liquidity)
        internal
        pure
        returns (uint256 amountB)
    {
        uint256 virtualReserve0 = (uint256(liquidity) << Constants.RESOLUTION) / sqrtRatioX96; // x = L / sqrt(P)
        uint256 virtualReserve1 = FullMath.mulDiv(liquidity, sqrtRatioX96, Constants.Q96); // y = L * sqrt(P)
        // note that vr0 * vr1 is safe from overflow since sqrt(vr0 * vr1) = L and liquidity is less than 2^128
        if (isToken0) {
            amountB = amountA * virtualReserve1 / virtualReserve0;
        } else {
            amountB = amountA * virtualReserve0 / virtualReserve1;
        }
    }

    /// @notice Computes the amount of token that should be swapped so that the maximum amount of liquidity is minted
    /// starting from a given amount of token0 or token1. Note that this assumes no price impact or trading fees.
    /// @param sqrtRatioX96 A sqrt price representing the current pool prices
    /// @param sqrtRatioAX96 A sqrt price representing the first tick boundary
    /// @param sqrtRatioBX96 A sqrt price representing the second tick boundary
    /// @param poolLiquidity The current liquidity of the pool
    /// @param amountA The amount of token0 or token1 that is available for swapping
    /// @param isToken0 A flag that indicates if the starting amount is token0
    /// @return amountToSwap The amount of token that should be swapped
    function onesidedMintPreview(
        uint160 sqrtRatioX96,
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint128 poolLiquidity,
        uint256 amountA,
        bool isToken0
    ) internal pure returns (uint256 amountToSwap) {
        if (sqrtRatioX96 <= sqrtRatioAX96) {
            // Only token0 can be added - if we have token1 all of it must be swapped to token0.
            amountToSwap = isToken0 ? 0 : amountA;
        } else if (sqrtRatioX96 < sqrtRatioBX96) {
            // Calculate what the equivalent amount in the other token is.
            uint256 amountB = getEquivalentAmount(amountA, isToken0, sqrtRatioX96, poolLiquidity);
            (uint256 amount0, uint256 amount1) = isToken0 ? (amountA, amountB) : (amountB, amountA);
            // Calculate the maximum amount of liquidity that could be added on either side.
            uint256 liquidity0 = getLiquidityForAmount0(sqrtRatioX96, sqrtRatioBX96, amount0);
            uint256 liquidity1 = getLiquidityForAmount1(sqrtRatioAX96, sqrtRatioX96, amount1);
            // We want to add x % of L0 and (1-x) % of L1 so that the liquidity amounts are equal.
            // x * L0 = (1-x) * L1 ... x = L1 / (L0 + L1)
            uint256 combinedLiquidity = liquidity0 + liquidity1;
            if (combinedLiquidity == 0) return 0;
            if (isToken0) {
                amountToSwap = amountA * liquidity1 / combinedLiquidity;
            } else {
                amountToSwap = amountA * liquidity0 / combinedLiquidity;
            }
        } else {
            // We can add only token1.
            amountToSwap = isToken0 ? amountA : 0;
        }
    }

    /// @notice Computes the amount of token that should be swapped so that the maximum amount of liquidity is minted
    /// starting from a given amount of token0 and token1
    /// @param sqrtRatioX96 A sqrt price representing the current pool prices
    /// @param sqrtRatioAX96 A sqrt price representing the first tick boundary
    /// @param sqrtRatioBX96 A sqrt price representing the second tick boundary
    /// @param poolLiquidity Current liquidity of the pool
    /// @param amount0 The amount of token0 that we want to add
    /// @param amount1 The amount of token1 that we want to add
    /// @return amountToSwap The amount of token that should be swapped
    /// @return zeroForOne A flag that indicates if the amount to swap is token0
    function maxMintPreview(
        uint160 sqrtRatioX96,
        uint160 sqrtRatioAX96,
        uint160 sqrtRatioBX96,
        uint128 poolLiquidity,
        uint256 amount0,
        uint256 amount1
    ) internal pure returns (uint256 amountToSwap, bool zeroForOne) {
        (, bool token1Remains, uint256 amountRemaining) =
            getLiquidityForAmounts(sqrtRatioX96, sqrtRatioAX96, sqrtRatioBX96, amount0, amount1);
        zeroForOne = !token1Remains;
        amountToSwap = onesidedMintPreview(
            sqrtRatioX96, sqrtRatioAX96, sqrtRatioBX96, poolLiquidity, amountRemaining, !token1Remains
        );
    }
}
