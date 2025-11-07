// SPDX-License-Identifier: MIT
// OpenZeppelin Contracts (last updated v5.1.0) (token/ERC20/ERC20.sol)

pragma solidity ^0.8.20;

import {ERC20,IERC20} from "./ERC20.sol";
import {Ownable} from "./Ownable.sol";

contract Token is ERC20, Ownable {
    uint256 public constant AMPLIFIED_BASE = 10000;
    uint256 public constant AMPLIFIED_DECIMALS = 1 * 10 ** 18;

    uint256 public tranferRestrictScale = 100;
    uint256 public tranferRestrictTime = 1 days;
    mapping(address => bool) public transferNotRestrict;
    mapping(address => uint256) public firstTranferTime;
    mapping(address => mapping(uint256 => uint256)) public culDayTranferAmount;
    mapping(address => mapping(uint256 => uint256)) public culDayMaxTranferAmount;

    /**
     * @dev Indicates an error related to the current `balance` of a `sender`. Used in transfers.
     * @param sender Address whose tokens are being transferred.
     * @param culMaxTransfer Current balance for the interacting account.
     * @param needed Minimum amount required to perform a transfer.
     */
    error InsufficientDayTransferBalance(address sender, uint256 culMaxTransfer, uint256 needed);

    constructor(address initialOwner) ERC20("98#", "98#") Ownable(initialOwner) {
        transferNotRestrict[initialOwner] = true;
        _mint(initialOwner, 100000000000 * 10 ** 18);
    }

    function getUserDayTranferAmount(address user) external view returns (uint256 culMaxTransfer) {
        if(firstTranferTime[user] == 0) {
            culMaxTransfer = IERC20(address(this)).balanceOf(user) * tranferRestrictScale / AMPLIFIED_BASE;
        } else {
            uint256 culDays = (block.timestamp - firstTranferTime[user]) / tranferRestrictTime;
            if(culDayMaxTranferAmount[user][culDays] == 0) {
                culMaxTransfer = IERC20(address(this)).balanceOf(user) * tranferRestrictScale / AMPLIFIED_BASE;
            } else {
                culMaxTransfer = culDayMaxTranferAmount[user][culDays] - culDayTranferAmount[user][culDays];
            }
        }
    }

    function transfer(address to, uint256 value) public override returns (bool) {
        address owner = _msgSender();
        if(!transferNotRestrict[owner]) {
            updataDayTransfer(owner,value);
        }
        _transfer(owner, to, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) public override returns (bool) {
        address spender = _msgSender();
        _spendAllowance(from, spender, value);
        if(!transferNotRestrict[from]) {
            updataDayTransfer(from,value);
        }
        _transfer(from, to, value);
        return true;
    }

    function updataDayTransfer(address user, uint256 value) private {
        uint256 culMaxTransfer;
        if(firstTranferTime[user] == 0) {
            culMaxTransfer = IERC20(address(this)).balanceOf(user) * tranferRestrictScale / AMPLIFIED_BASE;
            if(culMaxTransfer < value) {
                revert InsufficientDayTransferBalance(user,culMaxTransfer,value) ;
            }
            firstTranferTime[user] = block.timestamp;
            uint256 culDays = 0;
            culDayTranferAmount[user][culDays] = value;
            culDayMaxTranferAmount[user][culDays] = culMaxTransfer;
        } else {
            uint256 culDays = (block.timestamp - firstTranferTime[user]) / tranferRestrictTime;
            if(culDayMaxTranferAmount[user][culDays] == 0) {
                culMaxTransfer = IERC20(address(this)).balanceOf(user) * tranferRestrictScale / AMPLIFIED_BASE;
                culDayMaxTranferAmount[user][culDays] = culMaxTransfer;
            }
            culDayTranferAmount[user][culDays] += value;
            if(culDayTranferAmount[user][culDays] > culDayMaxTranferAmount[user][culDays]) {
                revert InsufficientDayTransferBalance(user,culDayMaxTranferAmount[user][culDays] - value,value);
            }
        }
    }

    function setTranferRestrictScale(uint256 tranferRestrictScale_) external onlyOwner {
        tranferRestrictScale = tranferRestrictScale_;
    }

    function setTransferNotRestrict(address addr_, bool enabl) external onlyOwner {
        transferNotRestrict[addr_] = enabl;
    }

    function setTransferNotRestrictTime(uint256 tranferRestrictTime_) external onlyOwner {
        tranferRestrictTime = tranferRestrictTime_;
    }

}