// SPDX-License-Identifier: Unlicensed
pragma solidity 0.8;

library Math {
    /// @notice Returns the absolute difference of two int24 numbers.
    function diff(int24 a, int24 b) internal pure returns (uint24) {
        return a > b ? uint24(a - b) : uint24(b - a);
    }

    /// @notice Returns the smaller of two uint256 numbers.
    function min(uint256 a, uint256 b) internal pure returns (uint256) {
        return a < b ? a : b;
    }
}
