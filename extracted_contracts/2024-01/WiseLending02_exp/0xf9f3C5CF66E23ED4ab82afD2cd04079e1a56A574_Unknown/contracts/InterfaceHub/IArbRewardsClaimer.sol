// SPDX-License-Identifier: -- WISE --

pragma solidity =0.8.23;

interface IArbRewardsClaimer{
    function claim(
        address _receiver,
        uint256 _accrued,
        bytes32[] calldata _proof
    )
        external;
}
