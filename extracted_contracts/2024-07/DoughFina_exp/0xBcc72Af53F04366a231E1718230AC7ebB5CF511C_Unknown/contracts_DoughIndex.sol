// SPDX-License-Identifier: BUSL-1.1
pragma solidity =0.8.24;

import "./DoughDsa.sol";
import "@openzeppelin/contracts/proxy/Clones.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts-upgradeable/proxy/utils/Initializable.sol";
import { IDoughIndex, IBorrowManagementConnector, CustomError } from "./Interfaces.sol";
import { DoughCore } from "./libraries/DoughCore.sol";

/**
* $$$$$$$\                                $$\             $$$$$$$$\ $$\                                                   
* $$  __$$\                               $$ |            $$  _____|\__|                                                  
* $$ |  $$ | $$$$$$\  $$\   $$\  $$$$$$\  $$$$$$$\        $$ |      $$\ $$$$$$$\   $$$$$$\  $$$$$$$\   $$$$$$$\  $$$$$$\  
* $$ |  $$ |$$  __$$\ $$ |  $$ |$$  __$$\ $$  __$$\       $$$$$\    $$ |$$  __$$\  \____$$\ $$  __$$\ $$  _____|$$  __$$\ 
* $$ |  $$ |$$ /  $$ |$$ |  $$ |$$ /  $$ |$$ |  $$ |      $$  __|   $$ |$$ |  $$ | $$$$$$$ |$$ |  $$ |$$ /      $$$$$$$$ |
* $$ |  $$ |$$ |  $$ |$$ |  $$ |$$ |  $$ |$$ |  $$ |      $$ |      $$ |$$ |  $$ |$$  __$$ |$$ |  $$ |$$ |      $$   ____|
* $$$$$$$  |\$$$$$$  |\$$$$$$  |\$$$$$$$ |$$ |  $$ |      $$ |      $$ |$$ |  $$ |\$$$$$$$ |$$ |  $$ |\$$$$$$$\ \$$$$$$$\ 
* \_______/  \______/  \______/  \____$$ |\__|  \__|      \__|      \__|\__|  \__| \_______|\__|  \__| \_______| \_______|
*                               $$\   $$ |                                                                                
*                               \$$$$$$  |                                                                                
*                                \______/                                                                                 
* 
* @title DoughIndex
* @notice This contract is used to manage the Dough Finance Settings and Connectors
* @custom:version 1.0 - Initial release
* @author Liberalite https://github.com/liberalite
* @custom:coauthor 0xboga https://github.com/0xboga
*/
contract DoughIndex is Initializable {
    using SafeERC20 for IERC20;

    /* ========== EVENTS ========== */
    event AllowOnlyEOA(bool status);
    event ApyFeeUpdated(uint256 apyFee);
    event DsaCreated(address indexed newDsaAddress, address indexed ownerAddress);
    event ConnectorUpdated(uint256 connectorId, address connectorAddress);
    event UpdateBorrowDate(address caller, address dsaAddress, address token, uint256 connector, uint256 timeNow);
    event NewTokenWhitelisted(address token, uint8 decimals, uint256 minInterest);
    event DeletedTokenWhitelisted(address token);
    event NewDoughMultisig(address newMultisig);
    event NewDoughIndex(address newDoughIndex);
    event NewMinHealthFactor(uint256 feeRatio);
    event NewDeleverageAsset(address deleverageAsset);
    event NewTreasuryAddress(address treasuryAddress);
    event NewDeleveragingRatio(uint256 minDeleveragingRatio);
    event NewDeleverageAutomation(address deleverageAutomation);
    event NewShieldAutomation(address shieldAutomation);
    event NewVaultAutomation(address vaultAutomation);
    event NewFlashBorrower(address flashBorrower, bool status);
    event NewBorrowFormula(address borrowFormula);
    event NewAaveActionsConnector(address aaveActionsConnector);
    event NewDsaMasterClone(address dsaMasterClone);

    /* ========== STORAGE VARIABLES ========== */
    bool public allowOnlyEOA;
    uint256 public apyFee;
    uint256 public dsaCounter;
    uint256 public minHealthFactor;
    uint256 public minDeleveragingRatio;

    address[] public whitelistedTokenList;
    address public dsaMasterCopy;
    address public multisig;
    address public treasury;
    address public deleverageAsset;
    address public borrowFormulaAddress;
    address public aaveActionsAddress;
    address public deleverageAutomation;
    address public shieldAutomation;
    address public vaultAutomation;

    /* ========== STRUCT ========== */
    struct WhitelistedTokens {
        uint8 decimals;
        uint256 minInterest;
        uint256 tokenIndex;
    }

    /* ========== MAPPINGS ========== */
    mapping(address => mapping(address => uint256)) private _dsaTokenBorrowStartDate;
    mapping(address => WhitelistedTokens) public whitelistedTokens;
    mapping(address => address) private getDsaOfOwner;
    mapping(address => address) public getOwnerOfDoughDsa;
    mapping(uint256 => address) public getDsaByID;
    mapping(uint256 => address) public getDoughConnector;
    mapping(address => bool) public getFlashBorrowers;

    /* ========== MODIFIERS ========== */
    modifier onlyMultisig {
        if(msg.sender != multisig) revert CustomError("Invalid multisig address");
        _;
    }

    /**
     * @notice Initialize the Dough Index contract
     * @param _multisig The address of the multisig
     * @param _treasury The address of the treasury
     * @param _deleveratingAsset The address of the preferred asset for deleveraging
     * @param _deleverageAutomation The address of the deleveraging automation contract
     * @param _apyFee The fee to be charged for the APY
     * @param _minDeleveragingRatio The minimum deleveraging ratio
     * @param _minHealthFactorRatio The minimum allowed health factor ratio
     */
    function initialize(
        address _multisig, 
        address _treasury, 
        address _deleveratingAsset, 
        address _deleverageAutomation, 
        uint256 _apyFee, 
        uint256 _minDeleveragingRatio, 
        uint256 _minHealthFactorRatio
    ) public initializer {
        deleverageAutomation = _deleverageAutomation;
        minDeleveragingRatio = _minDeleveragingRatio;
        minHealthFactor = _minHealthFactorRatio;
        deleverageAsset = _deleveratingAsset;
        multisig = _multisig;
        treasury = _treasury;
        apyFee = _apyFee;
        allowOnlyEOA = true;
    }

    /**
    * @notice Function to set new DSA Master Clone
    * @param _dsaMasterCopy The address of the new DSA Master Clone
    * @dev Only the multisig can call this function
    */
    function setDsaMasterClone(address _dsaMasterCopy) external onlyMultisig {
        if (_dsaMasterCopy == address(0)) revert CustomError("Invalid zero address");
        dsaMasterCopy = _dsaMasterCopy;
        emit NewDsaMasterClone(_dsaMasterCopy);
    }

    /**
    * @notice Function to set new recipe for the Dough Index Borrow Formula
    * @param _newBorrowFormula The address of the new borrow formula contract
    * @dev Only the multisig can call this function
    */
    function setNewBorrowFormula(address _newBorrowFormula) external onlyMultisig {
        if (_newBorrowFormula == address(0)) revert CustomError("Invalid zero address");
        borrowFormulaAddress = _newBorrowFormula;
        emit NewBorrowFormula(_newBorrowFormula);
    }
    
    /**
    * @notice Function to set new Aave Actions Connector
    * @param _newAaveActions The address of the new Aave Actions Connector
    * @dev Only the multisig can call this function
    */
    function setNewAaveActions(address _newAaveActions) external onlyMultisig {
        if (_newAaveActions == address(0)) revert CustomError("Invalid zero address");
        aaveActionsAddress = _newAaveActions;
        emit NewAaveActionsConnector(_newAaveActions);
    }

    /**
    * @notice Function to set new Deleveraging Automation
    * @param _deleverageAutomation The address of the new deleveraging automation contract
    * @dev Only the multisig can call this function
    */
    function setDeleverageAutomation(address _deleverageAutomation) external onlyMultisig {
        deleverageAutomation = _deleverageAutomation;
        emit NewDeleverageAutomation(_deleverageAutomation);
    }

    /**
    * @notice Function to set new Chainlink Shield Automation
    * @param _shieldAutomation The address of the new shield automation contract
    * @dev Only the multisig can call this function
    */
    function setNewShieldAutomation(address _shieldAutomation) external onlyMultisig {
        shieldAutomation = _shieldAutomation;
        emit NewShieldAutomation(_shieldAutomation);
    }

    /**
    * @notice Function to set new recipe for the Dough Index Borrow Formula
    * @param _vaultAutomation The address of the new borrow formula contract
    * @dev Only the multisig can call this function
    */
    function setNewVaultAutomation(address _vaultAutomation) external onlyMultisig {
        vaultAutomation = _vaultAutomation;
        emit NewVaultAutomation(_vaultAutomation);
    }

    /**
    * @notice Function to delete a whitelisted token address
    * @param _token The address of the token to be deleted
    * @dev Only the multisig can call this function
    */
    function deleteWhitelistedTokenAddress(address _token) external onlyMultisig {
        if (_token == address(0)) revert CustomError("Invalid zero address");
        uint256 lastKey = whitelistedTokenList.length - 1;
        address lastTokenAddress = whitelistedTokenList[lastKey];

        if(lastTokenAddress == _token) {
            whitelistedTokenList.pop();
            delete whitelistedTokens[_token];
            emit DeletedTokenWhitelisted(_token);
            return;
        }

        whitelistedTokens[lastTokenAddress].tokenIndex = lastKey;
        uint256 indexNr = whitelistedTokens[_token].tokenIndex;
        whitelistedTokenList[indexNr] = whitelistedTokenList[lastKey];
        whitelistedTokenList.pop();

        delete whitelistedTokens[_token];

        emit DeletedTokenWhitelisted(_token);
    }

    /**
    * @notice Function to set a new whitelisted token
    * @param _token The address of the token to be whitelisted
    * @param _decimals The decimals of the token
    * @param _minInterest The minimum interest of the token
    * @dev Only the multisig can call this function
    */
    function setNewWhitelistedToken(address _token, uint8 _decimals, uint256 _minInterest) external onlyMultisig {
        if (_token == address(0)) revert CustomError("Invalid zero address");
        if (_decimals == 0) revert CustomError("Invalid token decimals");
        whitelistedTokens[_token] = WhitelistedTokens(_decimals, _minInterest, whitelistedTokenList.length);
        whitelistedTokenList.push(_token);
        emit NewTokenWhitelisted(_token, _decimals, _minInterest);
    }

    /**
    * @notice Function to get the address of the DoughDsa contract
    * @param _flashBorrower The address of the flash borrower
    * @param _status The status of the flash borrower
    * @dev Only the multisig can call this function
    */
    function setFlashBorrower(address _flashBorrower, bool _status) public onlyMultisig {
        getFlashBorrowers[_flashBorrower] = _status;
        address dsa = getDsaOfOwner[_flashBorrower];
        uint256 whitelistedTokensLength = whitelistedTokenList.length;
        if(_status == true) {
            for (uint i = 0; i < whitelistedTokensLength;) {
                _dsaTokenBorrowStartDate[dsa][whitelistedTokenList[i]] = 0;
                unchecked { i++; }
            }
        }
        emit NewFlashBorrower(_flashBorrower, _status);
    }

    /**
    * Function to set the multiple flash borrowers
    * @param _flashBorrowers The addresses of the flash borrowers
    * @param _status The status of the flash borrowers
    * @dev Only the multisig can call this function
    */
    function setMultipleFlashBorrowers(address[] calldata _flashBorrowers, bool[] calldata _status) external onlyMultisig {
        for (uint256 i = 0; i < _flashBorrowers.length;) {
            setFlashBorrower(_flashBorrowers[i], _status[i]);
            unchecked { i++; }
        }
    }

    /**
    * @notice Function to set the minimum allowed health factor ratio
    * @param _minHealthFactor The minimum allowed health factor ratio
    * @dev Only the multisig can call this function
    */
    function setMinAllowedHealthFactorRatio(uint256 _minHealthFactor) external onlyMultisig {
        minHealthFactor = _minHealthFactor;
        emit NewMinHealthFactor(_minHealthFactor);
    }

    /**
    * @notice Function to set a new multisig for the Dough Index contract
    * @param _newMultiSig Only the multisig address can change the new multisig
    * @dev Only the multisig can call this function
    */
    function setNewMultisig(address _newMultiSig) external onlyMultisig {
        if (_newMultiSig == address(0)) revert CustomError("Invalid zero address");
        multisig = _newMultiSig;
        emit NewDoughMultisig(_newMultiSig);
    }

    /**
    * @notice Function to set the preferred asset for deleveraging
    * @param _deleverageAsset The address of the preferred asset for deleveraging
    * @dev Only the multisig can call this function
    */
    function updateDeleverageAsset(address _deleverageAsset) external onlyMultisig {
        if (_deleverageAsset == address(0)) revert CustomError("Invalid zero address");
        if (whitelistedTokens[_deleverageAsset].decimals == 0) revert CustomError("token is not whitelisted");
        deleverageAsset = _deleverageAsset;
        emit NewDeleverageAsset(_deleverageAsset);
    }

    /**
    * @notice Function to set the minimum deleveraging ratio
    * @param _minDeleveragingRatio The minimum deleveraging ratio
    * @dev Only the multisig can call this function
    */
    function setMinDeleveragingRatio(uint256 _minDeleveragingRatio) external onlyMultisig {
        minDeleveragingRatio = _minDeleveragingRatio;
        emit NewDeleveragingRatio(_minDeleveragingRatio);
    }

    /**
    * @notice Function to set the treasury address
    * @param _treasury The address of the treasury
    * @dev Only the multisig can call this function
    */
    function setTreasury(address _treasury) external onlyMultisig {
        if (_treasury == address(0)) revert CustomError("Invalid zero address");
        treasury = _treasury;
        emit NewTreasuryAddress(_treasury);
    }

    /**
    * @notice Function to set the APY fee
    * @param _apyFee The fee to be charged for the APY
    * @dev Only the multisig can call this function
    */
    function setApyFee(uint256 _apyFee) external onlyMultisig {
        apyFee = _apyFee;
        emit ApyFeeUpdated(_apyFee);
    }

    /**
    * @notice Function to set the connectors
    * @param _connectorId The ID of the connector
    * @param _connectorsAddr The address of the connector
    * @dev Only the multisig can call this function
    */
    function setConnectors(uint256 _connectorId, address _connectorsAddr) external onlyMultisig {
        getDoughConnector[_connectorId] = _connectorsAddr;
        emit ConnectorUpdated(_connectorId, _connectorsAddr);
    }

    /**
    * @notice Function to set only EOA
    * @param _status The status of the EOA
    * @dev Only the multisig can call this function
    */
    function setAllowOnlyEOA(bool _status) external onlyMultisig {
        allowOnlyEOA = _status;
        emit AllowOnlyEOA(_status);
    }

    /**
    * @notice Function to withdraw accidentaly sent ETH/ERC20 tokens to the connector
    * @param _asset The address of the ETH/ERC20 token
    * @param _treasury The address of the treasury
    * @param _amount The amount of ETH/ERC20 token to withdraw
    */
    function withdrawToken(address _asset, address _treasury, uint256 _amount) external onlyMultisig {
        if (_amount == 0) revert CustomError("must be greater than zero");
        if (_asset == DoughCore.ETH) {
            payable(_treasury).transfer(_amount);
        } else {
            uint256 balanceOfToken = IERC20(_asset).balanceOf(address(this));
            uint256 transferAmount = _amount;
            if (_amount > balanceOfToken) {
                transferAmount = balanceOfToken;
            }
            IERC20(_asset).safeTransfer(_treasury, transferAmount);
        }
    }

    /**
     * @notice Function to get the owner of the DSA
     * @param _dsaAddress The address of the DSA
     */
    function getDoughDsa(address _dsaAddress) external view returns (address) {
        return getDsaOfOwner[_dsaAddress];
    }

    /**
    * @notice Function to build a new DSA
    * @return address The address of the new DSA
    */
    function buildDoughDsa() external returns (address) {
        if (getDsaOfOwner[msg.sender] != address(0)) revert CustomError("DSA already created");
        if (allowOnlyEOA && isContract(msg.sender)) revert CustomError("DSA not contract-owned");
        address newDoughDsa = Clones.clone(dsaMasterCopy);
        DoughDsa(payable(newDoughDsa)).initialize(msg.sender, address(this));
        getDsaOfOwner[msg.sender] = newDoughDsa;
        getOwnerOfDoughDsa[newDoughDsa] = msg.sender;
        getDsaByID[dsaCounter] = newDoughDsa;
        dsaCounter++;
        emit DsaCreated(newDoughDsa, msg.sender);
        return address(newDoughDsa);
    }

    /**
    * @notice Function to get DSA token borrow start date
    * @param _dsaAddress The address of the DSA
    * @param _token The address of the token
    * @return uint256 The start date of the borrow
    */
    function getDsaBorrowStartDate(address _dsaAddress, address _token) external view returns (uint256) {
        return _dsaTokenBorrowStartDate[_dsaAddress][_token];
    }

    /**
    * @notice Function to get whitelisted token list
    * @return address[] The list of whitelisted tokens
    */
    function getWhitelistedTokenList() external view returns (address[] memory) {
        return whitelistedTokenList;
    }

    /**
    * @notice Function to get the token decimals
    * @param _token The address of the token
    * @return uint8 The decimals of the token
    */
    function getTokenDecimals(address _token) external view returns (uint8) {
        return whitelistedTokens[_token].decimals;
    }

    /**
    * @notice Function to get the token min interest
    * @param _token The address of the token
    * @return uint256 The minimum interest of the token
    */
    function getTokenMinInterest(address _token) external view returns (uint256) {
        return whitelistedTokens[_token].minInterest;
    }

    /**
    * @notice Function to get the token index
    * @param _token The address of the token
    * @return uint256 The index of the token
    */
    function getTokenIndex(address _token) external view returns (uint256) {
        return whitelistedTokens[_token].tokenIndex;
    }

    /**
    * @notice Function to update the borrow start date partially for a DSA account
    * @param _connectorID The ID of the connector
    * @param _time The backed time
    * @param _dsaAddress The address of the DSA account
    * @param _token The address of the token
    */
    function updateBorrowDate(uint256 _connectorID, uint256 _time, address _dsaAddress, address _token) external {
        address connector = getDoughConnector[_connectorID];
        if (msg.sender != _dsaAddress && msg.sender != connector) revert CustomError("Invalid Caller");

        // Check if the DSA is registered in the DoughIndex or not
        if (getOwnerOfDoughDsa[_dsaAddress] == address(0)) revert CustomError("Index DSA not found");

        _dsaTokenBorrowStartDate[_dsaAddress][_token] = _time;
        
        emit UpdateBorrowDate(msg.sender, _dsaAddress, _token, _connectorID, _time);
    }

    /**
     * @notice Calculates the current interest for a given DSA account.
     * @param _token The address of the token.
     * @param _dsaAddress The address of the DSA account.
     * @return _scaledInterest The interest accrued since the last update.
     */
    function borrowFormulaInterest (address _token, address _dsaAddress) external view returns (uint256 _scaledInterest) {
        return IBorrowManagementConnector(borrowFormulaAddress).borrowFormulaInterest(_token, _dsaAddress);
    }

    /**
     * @notice Calculates the current debt and interest for a given DSA account.
     * @param _token The address of the token.
     * @param _dsaAddress The address of the DSA account.
     * @return _debtAmount The current debt amount without interest.
     * @return _totalAmount The total debt amount including accrued interest.
     * @return _scaledInterest The interest accrued since the last update.
     * @return _minInterest The minimum interest amount for this token, for validation purposes.
     */
    function borrowFormula (address _token, address _dsaAddress) external view returns (uint256 _debtAmount, uint256 _totalAmount, uint256 _scaledInterest, uint256 _minInterest) {
        (uint256 currentVariableDebt, uint256 totalAmount, uint256 scaledInterest, uint256 minInterest) = IBorrowManagementConnector(borrowFormulaAddress).borrowFormula(_token, _dsaAddress);
        return (currentVariableDebt, totalAmount, scaledInterest, minInterest);
    }

    /**
     * @dev Checks if an address is a smart contract
     * @param addr The address to check
     * @return bool true if `addr` is a smart contract, false otherwise
     */
    function isContract(address addr) private view returns (bool) {
        uint32 size;
        assembly {
            size := extcodesize(addr)
        }
        return size > 0;
    }

    uint256[30] __gap; // Adjusted for new variable
}