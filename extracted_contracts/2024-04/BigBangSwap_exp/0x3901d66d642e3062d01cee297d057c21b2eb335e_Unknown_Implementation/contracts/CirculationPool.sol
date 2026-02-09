// SPDX-License-Identifier: MIT

pragma solidity >= 0.8.0;

import "@openzeppelin/contracts-upgradeable/security/ReentrancyGuardUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/token/ERC20/IERC20Upgradeable.sol";
import "@openzeppelin/contracts-upgradeable/token/ERC20/utils/SafeERC20Upgradeable.sol";
import "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import "@openzeppelin/contracts-upgradeable/utils/AddressUpgradeable.sol";

interface IStakingFactory {
    function startTime() external view returns (uint256);
}

contract CirculationPool is Initializable, OwnableUpgradeable, ReentrancyGuardUpgradeable{

    using SafeERC20Upgradeable for IERC20Upgradeable;
    using AddressUpgradeable for address;

    
    address public bbgToken;
    address public stakingFactory;
    uint256 public rate; // 80 = 0.8%
    uint256 public totalReleased;
    mapping (uint256 => uint256) dayReleased;

    event TokenReleased(address receiver, uint256 amount, uint256 timestamp);

    function initialize (
        address bbgAddress
    ) public initializer {
        __Ownable_init();
        __ReentrancyGuard_init();

        bbgToken = bbgAddress;
	rate = 80;
    }

    // released bbg token 
    function getToken(uint256 ts) external nonReentrant returns (uint256){
	require (msg.sender == stakingFactory, "only staking factory authorized");
	if (stakingFactory == address(0))
		return 0;
        require(
		ts > IStakingFactory(stakingFactory).startTime() && 
		ts < block.timestamp &&
		ts % 86400 == 0, "invalid timestamp");
	uint256 balance = IERC20Upgradeable(bbgToken).balanceOf(address(this));
        require(
		dayReleased[ts] == 0 && 
		balance > 0, "has released or insufficient tokens");

	uint256 amount = balance * rate / 10000;
	require(amount > 0, "insufficient token to release");

	dayReleased[ts] = amount;
        totalReleased += amount;
	
	IERC20Upgradeable(bbgToken).safeTransfer(stakingFactory, amount);

        emit TokenReleased(stakingFactory, amount, block.timestamp);

	return amount;
    }

    // admin functions
    function setStakingFactory(address factory) external onlyOwner {
	require(factory != address(0), "invalid factory address");
	stakingFactory = factory;
    }

    function setReleaseRate(uint256 _rate) external onlyOwner {
	require(_rate > 0 && _rate < 10000, "invalid rate");
	rate = _rate;
    }
}
