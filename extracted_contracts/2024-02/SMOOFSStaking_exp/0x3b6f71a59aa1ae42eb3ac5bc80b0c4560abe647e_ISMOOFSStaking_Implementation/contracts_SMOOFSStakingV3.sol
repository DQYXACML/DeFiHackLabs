// SPDX-License-Identifier: Two3 Labs
pragma solidity 0.8.20;

import {IERC721} from "@openzeppelin/contracts/interfaces/IERC721.sol";
import {IERC20} from "@openzeppelin/contracts/interfaces/IERC20.sol";
import {AccessControlUpgradeable} from "@openzeppelin/contracts-upgradeable/access/AccessControlUpgradeable.sol";
import {IERC721Receiver} from "@openzeppelin/contracts/interfaces/IERC721Receiver.sol";
import {ReentrancyGuardUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/ReentrancyGuardUpgradeable.sol";
import {OwnableUpgradeable} from "@openzeppelin/contracts-upgradeable/access/OwnableUpgradeable.sol";
import {PausableUpgradeable} from "@openzeppelin/contracts-upgradeable/utils/PausableUpgradeable.sol";
import {Initializable} from "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import {UUPSUpgradeable} from "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

contract SMOOFSStakingV3 is
    IERC721Receiver,
    Initializable,
    OwnableUpgradeable,
    AccessControlUpgradeable,
    PausableUpgradeable,
    UUPSUpgradeable,
    ReentrancyGuardUpgradeable
{
    using SafeERC20 for IERC20;

    // errors
    error StakingEnded();
    error StakeNFTLimit();
    error NonStakedNFT();
    error NotNFTOwner();
    error FutureTimestamp();
    error RequiredRewardDeposit();
    error RequiredForcedUnstaking();

    uint256 public constant AVERAGE_BLOCK_TIME = 2;

    enum NFTState {
        Staked,
        Unbonding,
        Free
    }

    IERC721 private nftCollection;
    IERC20 private rewardToken;

    uint256 public stakingEndTime;
    uint256 private unbondingPeriod;

    uint256 private rewardPerBlock;
    uint256 private earlyUnboundTax;
    uint256 private totalNFTStakeLimit;
    uint256 private nftStakeCarryAmount;

    struct StakeEntry {
        NFTState state;
        address owner;
        uint256 stakedAt;
        uint256 unbondingAt;
        uint256 lastClaimedBlock;
        // added variable to track user deposit
        uint256 nftCarryAmount;
    }

    uint256[] private trackedNFTs;
    address[] private trackedWallets;

    mapping(uint256 => StakeEntry) private stakes;
    mapping(address => uint256[]) private stakeOwnership;

    uint256 private stakesCount;
    uint256 private activeStakesCount;
    // added variable to check how many contract balance is deposits
    uint256 public usersDeposits;
    uint256 public stakingEndBlock;

    event StakingInfo(address user, uint256 tokenId, uint256 nftCarryAmount);
    event UnstakeInfo(address user, uint256 tokenId, bool forceTax);
    event WithdrawInfo(uint256 tokenId);
    event ClaimRewardInfo(uint256 tokenId, uint256 reward);
    event NewRewardPerBlock(uint256 newReward);
    event NewEarlyUnbondTax(uint256 newEarlyUnbondTax);
    event NewTotalNFTStakeLimit(uint256 newStakeLimit);
    event NewNFTStakeCarryAmount(uint256 newCarryAmount);
    event NewStakingEndTime(uint256 newStakingEndTime);
    event NewUnbondingPeriod(uint256 newUnbondingPeriod);

    // emergency events
    event ForcedWithdrawNFT(uint256 tokenId);
    event ForcedWithdrawRewardTokens();
    event SetStakingCount(uint256 count);
    event SetUsersDeposits(uint256 depositsAmount);
    event SetStakingEndBlock(uint256 endBlock);

    /// @custom:oz-upgrades-unsafe-allow constructor
    constructor() {
        _disableInitializers();
    }

    function initialize(
        address _nftCollectionAddress,
        address _rewardTokenAddress,
        uint256 _rewardPerBlock,
        uint256 _earlyUnbondTax,
        uint256 _totalNFTStakeLimit,
        uint256 _nftStakeCarryAmount,
        uint256 _stakingDuration,
        uint256 _unbondingPeriod
    ) external initializer {
        nftCollection = IERC721(_nftCollectionAddress);
        rewardToken = IERC20(_rewardTokenAddress);
        rewardPerBlock = _rewardPerBlock;
        earlyUnboundTax = _earlyUnbondTax;
        totalNFTStakeLimit = _totalNFTStakeLimit;
        nftStakeCarryAmount = _nftStakeCarryAmount;

        stakingEndTime = block.timestamp + _stakingDuration * 1 hours;
        unbondingPeriod = _unbondingPeriod * 1 hours;

        __Ownable_init(msg.sender);
        __AccessControl_init();
    }

    function Stake(uint256 _tokenId) public whenNotPaused {
        if (block.timestamp >= stakingEndTime) revert StakingEnded();
        if (activeStakesCount >= totalNFTStakeLimit) revert StakeNFTLimit();
        if (nftCollection.ownerOf(_tokenId) != msg.sender) revert NotNFTOwner();
        //transfer tokens to contract
        rewardToken.safeTransferFrom(msg.sender, address(this), nftStakeCarryAmount);
        //transfer nft to contract
        nftCollection.safeTransferFrom(msg.sender, address(this), _tokenId);
        activeStakesCount++;
        // add deposit to track
        usersDeposits += nftStakeCarryAmount;
        _addStake(
            _tokenId,
            StakeEntry({
                owner: msg.sender,
                nftCarryAmount: nftStakeCarryAmount,
                state: NFTState.Staked,
                stakedAt: block.timestamp,
                unbondingAt: 0,
                lastClaimedBlock: block.number
            })
        );
        emit StakingInfo(msg.sender, _tokenId, nftStakeCarryAmount);
    }

    function Unstake(uint256 _tokenId, bool forceWithTax) public whenNotPaused {
        if (block.timestamp >= stakingEndTime) revert StakingEnded();
        if (stakes[_tokenId].state != NFTState.Staked) revert NonStakedNFT();
        if (stakes[_tokenId].owner != msg.sender) revert NotNFTOwner();
        NFTState state = stakes[_tokenId].state;
        if (forceWithTax) {
            rewardToken.safeTransferFrom(msg.sender, address(this), earlyUnboundTax);
            state = NFTState.Free;
            stakes[_tokenId].unbondingAt = block.timestamp;
        } else {
            state = NFTState.Unbonding;
            stakes[_tokenId].unbondingAt = block.timestamp + unbondingPeriod;
        }
        ClaimReward(_tokenId);
        activeStakesCount--;
        stakes[_tokenId].state = state;

        emit UnstakeInfo(msg.sender, _tokenId, forceWithTax);
    }

    function Withdraw(uint256 _tokenId, bool forceWithTax) external whenNotPaused nonReentrant {
        if (stakes[_tokenId].owner != msg.sender) revert NotNFTOwner();
        if (block.timestamp < stakingEndTime) {
            // added check if unbondingAt = 0
            if (block.timestamp < stakes[_tokenId].unbondingAt || stakes[_tokenId].unbondingAt == 0) {
                if (forceWithTax != true) revert RequiredForcedUnstaking();
            }

            if (stakes[_tokenId].state == NFTState.Staked) {
                Unstake(_tokenId, forceWithTax);
            } else if (stakes[_tokenId].state == NFTState.Unbonding) {
                if (block.timestamp < stakes[_tokenId].unbondingAt) {
                    rewardToken.safeTransferFrom(msg.sender, address(this), earlyUnboundTax);
                }
            }
        } else if (stakes[_tokenId].state == NFTState.Staked) {
            _claim(_tokenId);
        }

        uint256 userDeposit = stakes[_tokenId].nftCarryAmount;
        if (userDeposit == 0) {
            userDeposit = nftStakeCarryAmount;
        }
        _removeStake(_tokenId);
        // remove carry amount from deposits track
        usersDeposits -= userDeposit;
        //transfer nft to owner
        nftCollection.safeTransferFrom(address(this), msg.sender, _tokenId);
        //transfer tokens to owner
        rewardToken.safeTransfer(msg.sender, userDeposit);

        emit WithdrawInfo(_tokenId);
    }

    function StakeList(address owner) public view returns (uint256[] memory) {
        return stakeOwnership[owner];
    }

    function StakeInfo(uint256 _tokenId) public view returns (StakeEntry memory) {
        return stakes[_tokenId];
    }

    function UnbondingInfo(uint256 _tokenId) public view returns (uint256) {
        return stakes[_tokenId].unbondingAt;
    }

    function RewardInfo(uint256 _tokenId) public view returns (uint256) {
        uint256 blockNumber = block.number;
        if (block.timestamp > stakingEndTime) {
            blockNumber = stakingEndBlock;
            if (stakes[_tokenId].lastClaimedBlock >= blockNumber) {
                return 0;
            }
        }

        uint256 blocksSinceLastClaimed = blockNumber - stakes[_tokenId].lastClaimedBlock;
        uint256 reward = blocksSinceLastClaimed * (rewardPerBlock / activeStakesCount);
        return reward;
    }

    function ClaimReward(uint256 _tokenId) public whenNotPaused {
        if (stakes[_tokenId].state != NFTState.Staked) revert NonStakedNFT();
        if (stakes[_tokenId].owner != msg.sender) revert NotNFTOwner();

        _claim(_tokenId);
    }

    function ClaimAllRewards() public whenNotPaused {
        uint arrayLength = stakeOwnership[msg.sender].length;
        for (uint256 i; i < arrayLength; i++) {
            uint256 _tokenId = stakeOwnership[msg.sender][i];
            if (stakes[_tokenId].state == NFTState.Staked) ClaimReward(_tokenId);
        }
    }

    function StakeCount(address owner) public view returns (uint256) {
        return stakeOwnership[owner].length;
    }

    function StakingEndTime() external view returns (uint256) {
        return stakingEndTime;
    }

    function UnbondingPeriod() external view returns (uint256) {
        return unbondingPeriod;
    }

    function RewardPerBlock() external view returns (uint256) {
        return rewardPerBlock;
    }

    function TrackedWallets() external view returns (address[] memory) {
        return trackedWallets;
    }

    function TrackedNFTs() external view returns (uint256[] memory) {
        return trackedNFTs;
    }

    function TotalStakes() external view returns (uint256) {
        return stakesCount;
    }

    function ActiveStakeCount() external view returns (uint256) {
        return activeStakesCount;
    }

    function TotalNFTStakeLimit() external view returns (uint256) {
        return totalNFTStakeLimit;
    }

    function NFTStakeCarryAmount() external view returns (uint256) {
        return nftStakeCarryAmount;
    }

    function EarlyUnboundTax() external view returns (uint256) {
        return earlyUnboundTax;
    }

    function RewardToken() external view returns (IERC20) {
        return rewardToken;
    }

    function NFTCollection() external view returns (IERC721) {
        return nftCollection;
    }

    function ForceWithdrawRewardTokens() external onlyOwner {
        rewardToken.safeTransfer(msg.sender, rewardToken.balanceOf(address(this)));

        emit ForcedWithdrawRewardTokens();
    }

    function ForceWithdrawNFT(uint256 _tokenId) external onlyOwner {
        nftCollection.safeTransferFrom(address(this), msg.sender, _tokenId);

        emit ForcedWithdrawNFT(_tokenId);
    }

    function _addStake(uint256 _tokenId, StakeEntry memory stakeEntry) private {
        stakes[_tokenId] = stakeEntry;
        stakeOwnership[stakeEntry.owner].push(_tokenId);
        _trackNFT(_tokenId);
        _trackWallet(stakeEntry.owner);
        stakesCount++;
    }

    function _removeStake(uint256 _tokenId) private {
        address owner = stakes[_tokenId].owner;
        //delete entry from stakeOwnership
        uint arrayLength = stakeOwnership[owner].length;
        for (uint256 i; i < arrayLength; i++) {
            if (stakeOwnership[owner][i] == _tokenId) {
                stakeOwnership[owner][i] = stakeOwnership[owner][arrayLength - 1];
                stakeOwnership[owner].pop();
                break;
            }
        }
        _untrackNFT(_tokenId);
        if (stakeOwnership[owner].length == 0) _untrackWallet(owner);
        delete stakes[_tokenId];
        stakesCount--;
    }

    function _trackNFT(uint256 _tokenId) private {
        bool found;
        uint arrayLength = trackedNFTs.length;
        for (uint256 i; i < arrayLength; i++) {
            if (trackedNFTs[i] == _tokenId) {
                found = true;
                break;
            }
        }
        if (!found) trackedNFTs.push(_tokenId);
    }

    function _untrackNFT(uint256 _tokenId) private {
        uint arrayLength = trackedNFTs.length;
        for (uint256 i; i < arrayLength; i++) {
            if (trackedNFTs[i] == _tokenId) {
                trackedNFTs[i] = trackedNFTs[arrayLength - 1];
                trackedNFTs.pop();
                break;
            }
        }
    }

    function _trackWallet(address _wallet) private {
        bool found;
        uint arrayLength = trackedWallets.length;
        for (uint256 i; i < arrayLength; i++) {
            if (trackedWallets[i] == _wallet) {
                found = true;
                break;
            }
        }
        if (!found) trackedWallets.push(_wallet);
    }

    function _untrackWallet(address _wallet) private {
        uint arrayLength = trackedWallets.length;
        for (uint256 i; i < arrayLength; i++) {
            if (trackedWallets[i] == _wallet) {
                trackedWallets[i] = trackedWallets[arrayLength - 1];
                trackedWallets.pop();
                break;
            }
        }
    }

    /// function to fix stakesCount after attack
    /// @param _value value to set before the hack
    /// @dev should be used one time to fix contract after hack
    function setStakingCount(uint256 _value) external onlyOwner {
        stakesCount = _value;

        emit SetStakingCount(_value);
    }

    /// function to set usersDeposits to track users funds on contract
    /// @param _value value of user deposits on contract
    /// @notice value should be set to: nft balance on contract * nftStakeCarryAmount
    /// @dev should be used one time before using contract
    function setUsersDeposits(uint256 _value) external onlyOwner {
        usersDeposits = _value;

        emit SetUsersDeposits(_value);
    }

    function setStakingEndBlock(uint256 _value) external onlyOwner {
        stakingEndBlock = _value;

        emit SetStakingEndBlock(_value);
    }

    function SetRewardPerBlock(uint256 _value) public onlyOwner {
        rewardPerBlock = _value;

        emit NewRewardPerBlock(_value);
    }

    function SetEarlyUnbondTax(uint256 _value) public onlyOwner {
        earlyUnboundTax = _value;

        emit NewEarlyUnbondTax(_value);
    }

    function SetTotalNFTStakeLimit(uint256 _value) public onlyOwner {
        totalNFTStakeLimit = _value;

        emit NewTotalNFTStakeLimit(_value);
    }

    function SetNFTStakeCarryAmount(uint256 _value) public onlyOwner {
        nftStakeCarryAmount = _value;

        emit NewNFTStakeCarryAmount(_value);
    }

    function SetStakingEndTime(uint256 _value) public onlyOwner {
        stakingEndTime = block.timestamp + _value * 1 hours;

        emit NewStakingEndTime(_value);
    }

    function SetUnbondingPeriod(uint256 _value) public onlyOwner {
        unbondingPeriod = _value * 1 hours;

        emit NewUnbondingPeriod(_value);
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    function _claim(uint256 _tokenId) internal {
        uint256 reward = RewardInfo(_tokenId);
        // add check if rewards will be taken from deposits
        if (rewardToken.balanceOf(address(this)) <= usersDeposits + reward) revert RequiredRewardDeposit();
        rewardToken.safeTransfer(msg.sender, reward);
        stakes[_tokenId].lastClaimedBlock = block.number;

        emit ClaimRewardInfo(_tokenId, reward);
    }

    function _authorizeUpgrade(address newImplementation) internal override onlyOwner {}

    function onERC721Received(address, address, uint256, bytes memory) public pure returns (bytes4) {
        return IERC721Receiver.onERC721Received.selector;
    }

    function calculateElapsedBlocksSinceTimestamp(uint256 pastTimestamp) public view returns (uint256) {
        if (pastTimestamp >= block.timestamp) revert FutureTimestamp();

        uint256 timeDiff = block.timestamp - pastTimestamp;
        uint256 elapsedBlocks = timeDiff / AVERAGE_BLOCK_TIME;
        return elapsedBlocks;
    }
}
