//  _____  _  _              _        _  ______        __                         _ 
// /  __ \(_)| |            | |      | | | ___ \      / _|                       | |
// | /  \/ _ | |_  __ _   __| |  ___ | | | |_/ / ___ | |_  ___  _ __  _ __  __ _ | |
// | |    | || __|/ _` | / _` | / _ \| | |    / / _ \|  _|/ _ \| '__|| '__|/ _` || |
// | \__/\| || |_| (_| || (_| ||  __/| | | |\ \|  __/| | |  __/| |   | |  | (_| || |
//  \____/|_| \__|\__,_| \__,_| \___||_| \_| \_|\___||_|  \___||_|   |_|   \__,_||_|

// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";

contract CitadelReferral is Ownable {
    //----------------------VARIABLES----------------------//

    struct Referral {
        address[] referrals;
        uint256[] timeOfReferrals;
    }

    mapping(address => string) private shortReferralCodes;
    mapping(string => address) private shortCodeOwners;

    mapping(address => bytes32) private bytesReferralCodes;
    mapping(bytes32 => address) private codeOwnersBytes;

    mapping(address => Referral) private referrals;
    mapping(address => address) private referrers;

    mapping(address => bool) private isAuthorized;
    bool public isStarted = false;

    uint256 private salt;

    address public CITStaking;

    //----------------------CONSTRUCTOR----------------------//

    constructor(address initialOwner) Ownable(initialOwner) {}

    //----------------------MODIFIERS----------------------//

    modifier onlyStaking() {
        require(
            msg.sender == CITStaking || msg.sender == owner(),
            "Only CITStaking can call this function"
        );
        _;
    }

    //----------------------SETTERS----------------------//

    function setCITStaking(address _CITStaking) public onlyOwner {
        CITStaking = _CITStaking;
    }

    function setIsStarted(bool _isStarted) public onlyOwner {
        isStarted = _isStarted;
    }

    function setIsAuthorizedBatch(address[] memory users, bool _isAuthorized)
        public
        onlyOwner
    {
        for (uint256 i = 0; i < users.length; i++) {
            isAuthorized[users[i]] = _isAuthorized;
        }
    }

    function setIsAuthorized(address user, bool _isAuthorized)
        public
        onlyOwner
    {
        isAuthorized[user] = _isAuthorized;
    }

    //----------------------USERS FUNCTIONS----------------------//

    /**
     * @dev generates a referral code for the caller
     */
    function generateReferralCode() public {
        require(isStarted || isAuthorized[msg.sender], "Not authorized");
        require(
            bytesReferralCodes[msg.sender] == 0,
            "Referral code already generated"
        );

        bytes32 referralCode;
        string memory shortCode;

        do {
            salt++;
            referralCode = keccak256(abi.encodePacked(msg.sender, salt));
            shortCode = _toShortCode(referralCode);
        } while (
            codeOwnersBytes[referralCode] != address(0) ||
                shortCodeOwners[shortCode] != address(0)
        );

        shortReferralCodes[msg.sender] = shortCode;
        shortCodeOwners[shortCode] = msg.sender;

        bytesReferralCodes[msg.sender] = referralCode;
        codeOwnersBytes[referralCode] = msg.sender;
    }

    /**
     * @dev uses a referral code to set the referrer of the caller
     * @param code the referral code to be used
     */
    function useReferralCode(string memory code) public {
        address _referrer = shortCodeOwners[code];
        require(_referrer != address(0), "Referral code does not exist");
        require(msg.sender != _referrer, "Cannot use your own referral code");
        require(
            referrers[msg.sender] == address(0),
            "Already used a referral code"
        );
        referrals[_referrer].referrals.push(msg.sender);
        referrals[_referrer].timeOfReferrals.push(block.timestamp);
        referrers[msg.sender] = _referrer;
    }

    //----------------------INTERNAL FUNCTIONS----------------------//

    function _toShortCode(bytes32 hashCode) private pure returns (string memory) {
        bytes memory alphabet = "0123456789abcdef";

        bytes memory str = new bytes(10);
        for (uint8 i = 0; i < 10; i++) {
            str[i] = alphabet[uint8(hashCode[i]) & 0x0f];
        }

        return string(str);
    }

    //----------------------GETTERS----------------------//

    function getUserFromCode(
        string memory code
    ) external view onlyStaking returns (address) {
        return shortCodeOwners[code];
    }

    function getReferrals(
        address user
    ) external view onlyStaking returns (address[] memory) {
        return referrals[user].referrals;
    }

    function getTimeOfReferrals(
        address user
    ) external view onlyStaking returns (uint256[] memory) {
        return referrals[user].timeOfReferrals;
    }

    /**
     * @dev gets the referral code of a user
     * @param user the user to get the referral code of
     */
    function getCodeFromUser(
        address user
    ) external view returns (string memory) {
        return shortReferralCodes[user];
    }

    /**
     * @dev gets the referrer of a user
     * @param user the user to get the referrer of
     */
    function getReferrer(address user) external view returns (address) {
        return referrers[user];
    }

    /**
     * @dev gets the amount of referrals a user has
     * @param user the user to get the amount of referrals of
     */
    function getAmountOfReferrals(address user)
        external
        view
        returns (uint256)
    {
        return referrals[user].referrals.length;
    }

    /**
     * @dev returns either if a user has a referral code or not
     * @param user the user to check
     */
    function getHasAReferralCode(address user) external view returns (bool) {
        return bytesReferralCodes[user] != 0;
    }
}
