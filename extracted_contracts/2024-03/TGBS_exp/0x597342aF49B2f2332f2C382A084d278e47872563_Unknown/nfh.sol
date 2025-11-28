// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/utils/Address.sol";

interface IPancakeRouter02 {
    function swapExactETHForTokensSupportingFeeOnTransferTokens(
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external payable;

    function WETH() external pure returns (address);
}

contract Dividend is Ownable {
    address public nftContractAddress1 =
        address(0x63EbEb811F43b1e65bAf7a7FD42c2113aed1ad1A);
    uint256 public lastTokenId1 = 198;
    address public nftContractAddress2 =
        address(0x015EB045Afb58e59a521047411224F9fc2331578);
    uint256 public lastTokenId2 = 398;
    IPancakeRouter02 public pancakeRouter =
        IPancakeRouter02(0x10ED43C718714eb63d5aA57B78B54704E256024E);
    IERC20 public token = IERC20(0xedecfA18CAE067b2489A2287784a543069f950F4);

    receive() external payable {}

    constructor() Ownable(msg.sender) {}

    function distributeDividends() external {
        swapBnbForToken(0, block.timestamp);
        uint256 totalReceived = token.balanceOf(address(this));
        require(totalReceived > 0, "No funds to distribute");
        distributeForNftContract(
            nftContractAddress1,
            lastTokenId1,
            totalReceived
        );
        distributeForNftContract(
            nftContractAddress2,
            lastTokenId2,
            totalReceived
        );
    }

    function swapBnbForToken(uint256 amountOutMin, uint256 deadline) public {
        address[] memory path = new address[](2);
        path[0] = pancakeRouter.WETH();
        path[1] = address(token);

        pancakeRouter.swapExactETHForTokensSupportingFeeOnTransferTokens{
            value: address(this).balance
        }(amountOutMin, path, address(this), deadline);
    }

    function distributeForNftContract(
        address nftContractAddress,
        uint256 lastTokenId,
        uint256 totalReceived
    ) private {
        IERC721 nftContract = IERC721(nftContractAddress);
        uint256 dividendAmount = totalReceived / 2 / (lastTokenId + 1);
        for (uint256 tokenId = 0; tokenId <= lastTokenId; tokenId++) {
            address tokenOwner = nftContract.ownerOf(tokenId);
            if (tokenOwner != address(0)) {
                token.transfer(tokenOwner, dividendAmount);
            }
        }
    }

    function updateNftContractAddresses(
        address _nftContractAddress1,
        address _nftContractAddress2
    ) external onlyOwner {
        nftContractAddress1 = _nftContractAddress1;
        nftContractAddress2 = _nftContractAddress2;
    }

    function setLast(uint256 _lastTokenId1, uint256 _lastTokenId2)
        external
        onlyOwner
    {
        lastTokenId1 = _lastTokenId1;
        lastTokenId2 = _lastTokenId2;
    }

    function withdrawToken(address _token) external onlyOwner {
        IERC20(_token).transfer(
            owner(),
            IERC20(_token).balanceOf(address(this))
        );
    }

    function withdraw() external onlyOwner {
        (bool sent, ) = owner().call{value: address(this).balance}("");
        require(sent, "Failed to send ETH");
    }
}
