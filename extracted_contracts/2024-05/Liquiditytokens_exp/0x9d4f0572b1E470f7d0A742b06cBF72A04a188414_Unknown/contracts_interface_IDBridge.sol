// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;



interface IDBridge  {
   

    event Deposit(
        bytes32 indexed bridgeId,
        uint256 indexed bridgeIndex,
        address sender,
        uint256 chainId,
        address tokenAddress,
        uint256 amount
    );

    event Bridge(
        bytes32 indexed bridgeId,
        uint256 sourceChainId,
        address receiver,
        address tokenAddress,
        uint256 amount,
        address[] validators
    );

    event Confirmation(
        bytes32 indexed bridgeId,
        uint256 sourceChainId,
        address receiver,
        address tokenAddress,
        uint256 amount,
        address confirmer
    );

    event Withdraw(
        bytes32 indexed bridgeId,
        address indexed receiver,
        address bridgeTokenAddress,
        uint256 amount
    );

   

    /**
     * @notice Deposit tokens into the bridge for cross-chain transfer.
     * @param chainId The ID of the target chain.
     * @param tokenAddress The address of the token being deposited.
     * @param amount The amount of tokens to deposit.
     * @return bridgeId The unique ID for the bridge transaction.
     */
    function deposit(
        uint256 chainId,
        address tokenAddress,
        uint256 amount
    ) external  returns (bytes32 bridgeId);

   

    /**
     * @notice Withdraw tokens from the bridge after all confirmations are received.
     * @param bridgeId The ID of the bridge transaction to withdraw from.
     */
    function withdraw(bytes32 bridgeId) external payable  ;

   
}
