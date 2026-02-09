// SPDX-License-Identifier: MIT

pragma solidity >= 0.8.0;

import "@openzeppelin/contracts-upgradeable/security/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/token/ERC20/IERC20Upgradeable.sol";
import "@openzeppelin/contracts-upgradeable/token/ERC20/utils/SafeERC20Upgradeable.sol";
import "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/utils/AddressUpgradeable.sol";

interface IBBGToken {
    function burn(uint amount) external returns (uint256);
}

contract ELPContract is Initializable, OwnableUpgradeable, ReentrancyGuardUpgradeable{

    using SafeERC20Upgradeable for IERC20Upgradeable;
    using AddressUpgradeable for address;

    struct UserInfo {
        uint256 totalStaked;
        uint256 totalReward;
        uint256 totalClaimed;
        uint256 updateTime;
        bool isUsed;
    }

    address private operator;
    address public bbgToken;
    address public lpToken;

    uint256 public totalStaked;
    uint256 public totalUnstaked;
    uint256 public totalClaimed;

    mapping(address => UserInfo) public userInfo;
    mapping(uint256 => uint256) public burnRecord;   			// hourly
    mapping(uint256 => uint256) public bbgBalanceHourly;		// hourly 
    mapping(uint256 => uint256) public bbgClaimedHourly;  		// hourly 
    mapping(address => mapping(uint256 => uint256)) public rewardRecord;// hourly

    uint256 public totalReward;
    uint256 public totalBurned;
   
    event Staked(address user, uint256 amount, uint256 timestamp);
    event Unstaked(address user, uint256 amount, uint256 leftAmount);
    event Claimed(address user, uint256 amount, uint256 timestamp);
    event HourlyRewarded(uint256 batchNo, uint256 amount, uint256 timestamp); 
    event HourlyBurned(uint256 hourly_ts, uint256 amount, uint256 timestamp);

    function initialize (
        address bbgAddress,
        address lpAddress,
	address operatorAddress
    ) public initializer {
        __Ownable_init();
        __ReentrancyGuard_init();

        bbgToken = bbgAddress;
        lpToken = lpAddress;
	operator = operatorAddress;
    }

    modifier onlyOperator() {
        require(msg.sender == owner() || msg.sender == operator, "only operator or owner authorized");
        _;
    }

    // get current LP token staked of user  
    function staked(address user) external view returns (uint256) {
        if (userInfo[user].isUsed)
            return userInfo[user].totalStaked;
        return 0;
    }

    // get total bbg reward (claimed included) 
    function rewarded(address user) external view returns (uint256) {
	    UserInfo memory info = userInfo[user];
        if (info.isUsed)
            return info.totalReward;
        return 0;
    }

    // get total bbg reward claimed  
    function claimed(address user) external view returns (uint256) {
	    UserInfo memory info = userInfo[user];
        if (info.isUsed)
            return info.totalClaimed;
        return 0;
    }

    // get available bbg reward (now) 
    function availableReward(address user) external view returns (uint256) {
	    UserInfo memory info = userInfo[user];
        if (info.isUsed)
            return info.totalReward - info.totalClaimed;
        return 0;
    }

    // stake LP token 
    function stake(uint256 amount) external nonReentrant {
        require(amount <= IERC20Upgradeable(lpToken).balanceOf(msg.sender), "transfer amount exceeds balance");

        IERC20Upgradeable(lpToken).safeTransferFrom(msg.sender, address(this), amount);

        UserInfo memory oldInfo = userInfo[msg.sender];
        if(oldInfo.isUsed)
        {
        	UserInfo memory newInfo = UserInfo(
            		oldInfo.totalStaked + amount,
			        oldInfo.totalReward,
			        oldInfo.totalClaimed,
            		block.timestamp,
            		true
        	);
        	userInfo[msg.sender] = newInfo;
        } else {
        	UserInfo memory newInfo = UserInfo(
            	amount,
			    0,
			    0,
                block.timestamp,
                true
        	);
        	userInfo[msg.sender] = newInfo;
	    }

        totalStaked += amount;

        emit Staked(msg.sender, amount, block.timestamp);
    }

    // unstake LP token 
    function unstake(uint256 amount) external nonReentrant{
        UserInfo storage info = userInfo[msg.sender];
        require(info.isUsed == true, "no stake record");
        require(amount > 0 && info.totalStaked >= amount, "not enough lp to unstake");

        info.totalStaked -= amount;
        info.updateTime = block.timestamp;

        totalStaked -= amount;
        totalUnstaked += amount;
	
	IERC20Upgradeable(lpToken).safeTransfer(msg.sender, amount);

        emit Unstaked(msg.sender, amount, info.totalStaked);
    }

    // claim reward token 
    function claim(uint256 amount) external nonReentrant{
        UserInfo storage info = userInfo[msg.sender];
        require(info.isUsed == true, "no stake record");
        require(amount > 0 && info.totalReward - info.totalClaimed >= amount, "not enough reward to claim");

        info.totalClaimed += amount;
        info.updateTime = block.timestamp;
        
        totalClaimed += amount;

        uint256 hourTimestamp = block.timestamp - block.timestamp % 3600;
        bbgClaimedHourly[hourTimestamp] += amount;

        IERC20Upgradeable(bbgToken).safeTransfer(msg.sender, amount);
        
        emit Claimed(msg.sender, amount, block.timestamp);
    }

    // ---- operator functions  ----
    function burnBBGHourly(uint256 ts, uint256 amount) external onlyOperator nonReentrant {
        require(ts%3600 == 0 && ts < block.timestamp, "invalid timestamp");
        require(burnRecord[ts] == 0, "already burned");

        IBBGToken(bbgToken).burn(amount);
        burnRecord[ts] = amount;
	totalBurned += amount;

        bbgBalanceHourly[ts] = IERC20Upgradeable(bbgToken).balanceOf(address(this));

        emit HourlyBurned(ts, amount, block.timestamp);
    }

    function rewardBBGHourly(uint256 batchNo, uint256 ts, address[] calldata accounts, uint256[] calldata values) external onlyOperator nonReentrant {
        require(ts%3600 == 0 && ts < block.timestamp, "invalid timestamp");
        require(accounts.length == values.length && accounts.length > 0, "accounts and values mismatch");

        uint256 amount = 0;
        for (uint i = 0; i < accounts.length; i++) {
            amount += values[i];
	    totalReward += values[i];
            UserInfo storage info = userInfo[accounts[i]];
            if (info.isUsed == false || rewardRecord[accounts[i]][ts] > 0)
                continue;
            info.totalReward += values[i];
            info.updateTime = block.timestamp;
            rewardRecord[accounts[i]][ts] = amount;
        }
        emit HourlyRewarded(batchNo, amount, ts);
    }
}
