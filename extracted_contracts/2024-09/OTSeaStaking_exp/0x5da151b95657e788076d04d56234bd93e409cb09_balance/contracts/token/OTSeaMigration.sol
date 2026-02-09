/*
        [....     [... [......  [.. ..
      [..    [..       [..    [..    [..
    [..        [..     [..     [..         [..       [..
    [..        [..     [..       [..     [.   [..  [..  [..
    [..        [..     [..          [.. [..... [..[..   [..
      [..     [..      [..    [..    [..[.        [..   [..
        [....          [..      [.. ..    [....     [.. [...

    Beta -> V1 Migration.

    https://otsea.io
    https://t.me/OTSeaPortal
    https://twitter.com/OTSeaERC20
*/

// SPDX-License-Identifier: MIT
pragma solidity =0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/interfaces/draft-IERC6093.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/cryptography/MerkleProof.sol";
import "@uniswap/v2-periphery/contracts/interfaces/IUniswapV2Router02.sol";
import "contracts/helpers/ListHelper.sol";
import "contracts/helpers/TransferHelper.sol";
import "contracts/libraries/OTSeaErrors.sol";
import "contracts/libraries/OTSeaLibrary.sol";

/**
 * @notice OTSea one-way beta -> v1 migration contract
 * @dev This contract facilitates the migration from the current (beta) token to the new v1 token.
 *
 * Migration steps:
 * 1. The team coordinate whales to approve the smart contract.
 * 2. The team will take a snapshot of the holder's balances of the beta token and generate a merkle tree. From this
 * merkle tree we can get the root.
 * 3. The root is uploaded into the contract (can only be done once).
 * 4. The team uses the smart contract to sell the approved tokens in Step 1, with the aim of gathering as much ETH
 *    as possible so that it can be used to fund the v1 liquidity pool. All whales participating receive a credit as
 *    opposed to receiving the v1 token straight away.
 * 5. The team deploys and adds the v1 token address in the contract. The purpose of not deploying the v1 contract in a
 *    prior step is because Etherscan will show that the OTSea deployer has deployed a new token which could affect the
 *    amount of ETH received in Step 4 (depending on if the community sees the new token deployed).
 * 6. Upon configuring the v1 token, users can then migrate their tokens from the beta token to the v1 token using
 *    a merkle proof via the migrate() function (on the dApp). The coordinated whales that received a credit in Step 4
 *    can claim their v1 tokens via the claimCredit() function. Also the team can claim tokens for addresses that can't
 *    claim for themselves, these are known as special addresses.
 *
 * The following addresses are special address:
 * - OTSeaERC20: 0x37DA9DE38c4094e090c014325f6eF4baEB302626
 * - Dead address: 0x000000000000000000000000000000000000dEaD
 * - OTSea (platform): 0x28A2F7849f0a2BCCf1F5D246cEf5a6867A5BFa23
 * - Uniswap V2 pair (OTSea/WETH): 0xd46934919D9138d3005C1f8Db794f03E7415bAbD
 *
 * Note: Any tokens in the current (beta) OTSea (platform) contract will be claimed by the team (as per Step 6) and
 * manually transferred to the relevant order creator(s).
 */
contract OTSeaMigration is Ownable, TransferHelper, ListHelper {
    using SafeERC20 for IERC20;

    struct Migration {
        address wallet;
        /// @dev amount to migrate
        uint256 amount;
        /// @dev amount recorded on snapshot (used to reconstruct the leaf)
        uint256 snapshot;
        bytes32[] proof;
    }

    IUniswapV2Router02 private constant _router =
        IUniswapV2Router02(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D);
    address private constant BETA_PAIR_ADDRESS = 0xd46934919D9138d3005C1f8Db794f03E7415bAbD;
    address private constant BETA_OTSEA_PLATFORM = 0x28A2F7849f0a2BCCf1F5D246cEf5a6867A5BFa23;
    IERC20 private constant _beta = IERC20(0x37DA9DE38c4094e090c014325f6eF4baEB302626);
    uint24 private constant MIGRATION_PERIOD = 90 days;
    address public immutable multiSigAdmin;
    IERC20 public v1;
    address public treasury;
    bool public hasLiquidityBeenExtracted;
    uint32 public migrationDeadline;
    bytes32 public merkleRoot;
    mapping(address => uint256) private _migrated;
    mapping(address => uint256) private _credit;

    error InvalidRoot();
    error InvalidProof();
    error InvalidMinETHAmount();
    error AmountExceedsSnapshot();
    error RootNotUploaded();

    event MerkleRootUploaded(bytes32 root);
    event Migrated(address indexed account, Migration migration);
    event CreditClaimed(address indexed account, uint256 credit);
    event V1TokenConfigured(address token, uint32 migrationDeadline);
    event ExtractedLiquidity(Migration[] migrations, uint256 amountSold, uint256 ethReceived);
    event SoldBetaTokens(uint256 amountSold, uint256 ethReceived);
    event ClaimedUnclaimedV1Tokens(uint256 amount);

    modifier canMigrate() {
        _checkCanMigrate();
        _;
    }

    modifier afterRootUploaded() {
        _checkRootUploaded();
        _;
    }

    /**
     * @param _multiSigAdmin Multi-sig admin
     * @param _migrationHandler Migration handler
     */
    constructor(address _multiSigAdmin, address _migrationHandler) Ownable(_migrationHandler) {
        if (_multiSigAdmin == address(0)) revert OTSeaErrors.InvalidAddress();
        multiSigAdmin = _multiSigAdmin;
    }

    /**
     * @notice Upload the merkle root, can only be uploaded once
     * @param _merkleRoot Merkle root
     */
    function uploadMerkleRoot(bytes32 _merkleRoot) external onlyOwner {
        if (_isRootUploaded()) revert OTSeaErrors.NotAvailable();
        if (_merkleRoot == bytes32(0)) revert InvalidRoot();
        merkleRoot = _merkleRoot;
        emit MerkleRootUploaded(_merkleRoot);
    }

    /**
     * @notice Extract liquidity by selling tokens from whales that have approved this contract
     * @param _migrations Migrations
     * @param _minETHAmount Minimum ETH to receive from selling
     * @dev this function can only be called once
     */
    function extractLiquidity(
        Migration[] calldata _migrations,
        uint256 _minETHAmount
    ) external onlyOwner afterRootUploaded {
        if (hasLiquidityBeenExtracted) revert OTSeaErrors.NotAvailable();
        uint256 length = _migrations.length;
        _validateListLength(length);
        if (_minETHAmount == 0) revert InvalidMinETHAmount();
        hasLiquidityBeenExtracted = true;
        uint256 betaBalanceBefore = _beta.balanceOf(address(this));
        for (uint256 i; i < length; ) {
            if (_migrations[i].wallet == address(0)) revert OTSeaErrors.InvalidAddressAtIndex(i);
            if (_credit[_migrations[i].wallet] != 0) revert OTSeaErrors.DuplicateAddressAtIndex(i);
            _validateMigration(_migrations[i]);
            _checkSufficientAmount(_migrations[i]);
            _credit[_migrations[i].wallet] = _migrations[i].amount;
            _beta.safeTransferFrom(_migrations[i].wallet, address(this), _migrations[i].amount);
            unchecked {
                i++;
            }
        }
        uint256 amountToSell = _beta.balanceOf(address(this)) - betaBalanceBefore;
        uint256 ethReceived = _sell(amountToSell, _minETHAmount);
        emit ExtractedLiquidity(_migrations, amountToSell, ethReceived);
    }

    /**
     * @notice Configure the contract to add the v1 token, doing so will allow users to migrate
     * @param _token Token Migrations
     * @dev this function can only be called once
     */
    function configureV1Token(IERC20 _token) external onlyOwner {
        /// @dev Liquidity has to have been extracted first, v1 cannot already be configured
        if (!hasLiquidityBeenExtracted || address(v1) != address(0))
            revert OTSeaErrors.NotAvailable();
        if (address(_token) == address(0)) revert OTSeaErrors.InvalidAddress();
        v1 = _token;
        /// @dev Set the deadline for migration to be 90 days after the v1 token has been configured
        migrationDeadline = uint32(block.timestamp + MIGRATION_PERIOD);
        emit V1TokenConfigured(address(_token), migrationDeadline);
    }

    /**
     * @notice Claim v1 tokens for special addresses
     * @param _specialMigrations Special migrations
     */
    function claimSpecialAddresses(
        Migration[] calldata _specialMigrations
    ) external onlyOwner canMigrate {
        uint256 length = _specialMigrations.length;
        _validateListLength(length);
        uint256 totalAmount;
        for (uint256 i; i < length; ) {
            Migration calldata migration = _specialMigrations[i];
            if (
                migration.wallet == address(_beta) ||
                migration.wallet == BETA_PAIR_ADDRESS ||
                migration.wallet == BETA_OTSEA_PLATFORM ||
                migration.wallet == OTSeaLibrary.DEAD_ADDRESS
            ) {
                _validateMigration(migration);
                _migrated[migration.wallet] += migration.amount;
                totalAmount += migration.amount;
                emit Migrated(migration.wallet, migration);
            } else {
                /// @dev revert due to _specialMigrations containing a migration for a non-special wallet
                revert OTSeaErrors.InvalidAddressAtIndex(i);
            }
            unchecked {
                i++;
            }
        }
        /// @dev special addresses do not receive their tokens and instead the multi-sig receives them
        v1.safeTransfer(multiSigAdmin, totalAmount);
    }

    /// @notice Claim v1 credit (only for users that took part in the liquidity extraction)
    function claimCredit() external canMigrate {
        uint256 credit = _credit[_msgSender()];
        if (credit == 0) revert OTSeaErrors.NotAvailable();
        _credit[_msgSender()] = 0;
        /// @dev update _migrated[_msgSender()] so that they cannot reclaim the credit amount using migrate()
        _migrated[_msgSender()] += credit;
        v1.safeTransfer(_msgSender(), credit);
        emit CreditClaimed(_msgSender(), credit);
    }

    /**
     * @notice Swap beta tokens for ETH, to be used by the owner
     * @param _amountToSell Amount of beta tokens to sell
     * @param _minETHAmount Minimum ETH to receive from selling
     */
    function sellBetaTokens(uint256 _amountToSell, uint256 _minETHAmount) external onlyOwner {
        if (_amountToSell == 0 || _beta.balanceOf(address(this)) < _amountToSell)
            revert OTSeaErrors.InvalidAmount();
        if (_minETHAmount == 0) revert InvalidMinETHAmount();
        uint256 ethReceived = _sell(_amountToSell, _minETHAmount);
        emit SoldBetaTokens(_amountToSell, ethReceived);
    }

    /// @notice After 90 days, any unclaimed tokens are available to be claimed by the multi-sig admin
    function claimUnclaimedV1Tokens() external {
        if (_msgSender() != multiSigAdmin) revert OTSeaErrors.Unauthorized();
        if (address(v1) == address(0)) revert OTSeaErrors.NotAvailable();
        uint256 amountToClaim = v1.balanceOf(address(this));
        /// @dev If the deadline has not been reached yet or it has but the amount to claim is 0, it reverts
        if (!_isDeadlineReached() || amountToClaim == 0) revert OTSeaErrors.NotAvailable();
        v1.safeTransfer(multiSigAdmin, amountToClaim);
        emit ClaimedUnclaimedV1Tokens(amountToClaim);
    }

    /**
     * @notice Migrate beta -> v1 tokens provided a valid merkle proof is present
     * @param _migration Migration
     */
    function migrate(Migration calldata _migration) external canMigrate {
        /// @dev if credit is owed it must first be claimed
        if (_credit[_msgSender()] != 0) revert OTSeaErrors.NotAvailable();
        if (_migration.wallet != _msgSender()) revert OTSeaErrors.Unauthorized();
        _validateMigration(_migration);
        _checkSufficientAmount(_migration);
        _migrate(_migration);
    }

    /**
     * @notice Get the amount migrated by an address
     * @param _account Account
     * @return uint256 Amount migrated by _account
     */
    function getMigratedAmountByAddress(address _account) external view returns (uint256) {
        return _migrated[_account];
    }

    /**
     * @notice Get the amount of v1 credit owed to an address
     * @param _account Account
     * @return uint256 Amount of credited owed to _account
     */
    function getCreditAmountByAddress(address _account) external view returns (uint256) {
        return _credit[_account];
    }

    /// @param _migration Migration
    function _migrate(Migration calldata _migration) private {
        _migrated[_migration.wallet] += _migration.amount;
        _beta.safeTransferFrom(_migration.wallet, address(this), _migration.amount);
        v1.safeTransfer(_migration.wallet, _migration.amount);
        emit Migrated(_migration.wallet, _migration);
    }

    /**
     * @param _amountToSell Amount of beta tokens to sell
     * @param _minETHAmount Minimum ETH to receive from selling
     * @return received Amount of ETH received for selling _amountToSell beta tokens
     */
    function _sell(uint _amountToSell, uint _minETHAmount) private returns (uint256 received) {
        address[] memory path = new address[](2);
        path[0] = address(_beta);
        path[1] = _router.WETH();
        _beta.forceApprove(address(_router), _amountToSell);
        uint256 ethBefore = multiSigAdmin.balance;
        _router.swapExactTokensForETHSupportingFeeOnTransferTokens(
            _amountToSell,
            _minETHAmount,
            path,
            multiSigAdmin,
            block.timestamp
        );
        received = multiSigAdmin.balance - ethBefore;
    }

    /// @param _migration Migration
    function _validateMigration(Migration calldata _migration) private view {
        if (_migration.proof.length == 0) revert InvalidProof();
        if (_migration.amount == 0 || _migration.snapshot == 0) revert OTSeaErrors.InvalidAmount();
        if (_migration.snapshot < _migrated[_migration.wallet] + _migration.amount)
            revert AmountExceedsSnapshot();
        bytes32 leaf = keccak256(abi.encodePacked(_migration.wallet, _migration.snapshot));
        bool isValidProof = MerkleProof.verifyCalldata(_migration.proof, merkleRoot, leaf);
        if (!isValidProof) revert InvalidProof();
    }

    /// @param _migration Migration
    function _checkSufficientAmount(Migration calldata _migration) private view {
        if (_beta.balanceOf(_migration.wallet) < _migration.amount)
            revert IERC20Errors.ERC20InsufficientBalance(
                _migration.wallet,
                _beta.balanceOf(_migration.wallet),
                _migration.amount
            );
        if (_beta.allowance(_migration.wallet, address(this)) < _migration.amount)
            revert IERC20Errors.ERC20InsufficientAllowance(
                address(this),
                _beta.allowance(_migration.wallet, address(this)),
                _migration.amount
            );
    }

    function _checkCanMigrate() private view {
        /// @dev check if the token has been configured and the deadline has not been reached
        if (address(v1) == address(0) || _isDeadlineReached()) revert OTSeaErrors.NotAvailable();
    }

    function _checkRootUploaded() private view {
        if (!_isRootUploaded()) revert RootNotUploaded();
    }

    /// @return bool true if the deadline has been reached, false if not
    function _isDeadlineReached() private view returns (bool) {
        return migrationDeadline < block.timestamp;
    }

    /// @return bool true if root has been uploaded, false if not
    function _isRootUploaded() private view returns (bool) {
        return merkleRoot != bytes32(0);
    }
}
