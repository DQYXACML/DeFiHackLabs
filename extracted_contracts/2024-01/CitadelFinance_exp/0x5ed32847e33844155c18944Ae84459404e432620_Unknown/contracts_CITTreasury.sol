//  _____  _  _              _        _   _____                                          
// /  __ \(_)| |            | |      | | |_   _|                                         
// | /  \/ _ | |_  __ _   __| |  ___ | |   | | _ __  ___   __ _  ___  _   _  _ __  _   _ 
// | |    | || __|/ _` | / _` | / _ \| |   | || '__|/ _ \ / _` |/ __|| | | || '__|| | | |
// | \__/\| || |_| (_| || (_| ||  __/| |   | || |  |  __/| (_| |\__ \| |_| || |   | |_| |
//  \____/|_| \__|\__,_| \__,_| \___||_|   \_/|_|   \___| \__,_||___/ \__,_||_|    \__, |
//                                                                                  __/ |
//                                                                                 |___/ 

// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "./interfaces/ICamelotRouter.sol";
import "./interfaces/IWETH.sol";

contract CitadelTreasury is Ownable {
    //----------------------VARIABLES----------------------//

    address public USDC;
    IWETH public WETH;
    ICamelotRouter public camelotRouter;
    address public CITRedeem;

    uint256 public amountRedeemedUSDC = 0;
    uint256 public amountRedeemedETH = 0;

    //----------------------CONSTRUCTOR----------------------//

    constructor(address initialOwner) Ownable(initialOwner) {
        USDC = 0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8; // 0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8
        WETH = IWETH(0x82aF49447D8a07e3bd95BD0d56f35241523fBab1); // 0x82aF49447D8a07e3bd95BD0d56f35241523fBab1
        camelotRouter = ICamelotRouter(
            0xc873fEcbd354f5A56E00E710B90EF4201db2448d
        ); // Camelot Arbitrum One 0xc873fEcbd354f5A56E00E710B90EF4201db2448d
    }

    //----------------------SETTERS----------------------//

    function setCITRedeem(address _CITRedeem) public onlyOwner {
        CITRedeem = _CITRedeem;
    }

    //----------------------USERS FUNCTIONS----------------------//

    /**
     * @param token the address of the token to be distributed
     * @param amount the amount of the token to be distributed
     * @param user the address of the user to receive the tokens
     */
    function distributeRedeem(
        address token,
        uint256 amount,
        address user
    ) public {
        require(
            msg.sender == CITRedeem,
            "Only CITRedeem can call this function"
        );
        require(IERC20(token).balanceOf(address(this)) >= amount, "Not enough tokens in treasury");
        if (token == USDC) {
            amountRedeemedUSDC += amount;
        } else if (token == address(WETH)) {
            amountRedeemedETH += amount;
        }
        IERC20(token).transfer(user, amount);
        if (address(this).balance > 0) {
            _wrapETH();
        }
    }

    //----------------------OWNER FUNCTIONS----------------------//

    function withdrawERC20(address token, uint256 amount) public onlyOwner {
        IERC20(token).transfer(msg.sender, amount);
    }

    function withdrawETH(uint256 amount) public onlyOwner {
        bool tmpSuccess;
        (tmpSuccess, ) = payable(msg.sender).call{value: amount, gas: 30000}(
            ""
        );
    }

    function swapWETHForUSDC(uint256 amount) public onlyOwner {
        address[] memory path = new address[](2);
        path[0] = address(WETH);
        path[1] = USDC;
        WETH.approve(address(camelotRouter), amount);
        camelotRouter.swapExactTokensForTokensSupportingFeeOnTransferTokens(
            amount,
            0,
            path,
            address(this),
            address(0),
            block.timestamp
        );
    }

    function swapUSDCForWETH(uint256 amount) public onlyOwner {
        address[] memory path = new address[](2);
        path[0] = USDC;
        path[1] = address(WETH);
        IERC20(USDC).approve(address(camelotRouter), amount);
        camelotRouter.swapExactTokensForTokensSupportingFeeOnTransferTokens(
            amount,
            0,
            path,
            address(this),
            address(0),
            block.timestamp
        );
    }

    //----------------------INTERNAL FUNCTIONS----------------------//

    receive() external payable {}

    function _wrapETH() internal {
        uint256 amount = address(this).balance;
        if (amount > 0) {
            WETH.deposit{value: amount}();
        }
    }
}
