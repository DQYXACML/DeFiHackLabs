// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20 {
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address recipient, uint256 amount) external returns (bool);
   
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);
    event InterestRateChanged(uint256 newRate);
}

abstract contract ReentrancyGuard {

    uint256 private constant _NOT_ENTERED = 1;
    uint256 private constant _ENTERED = 2;

    uint256 private _status;

    constructor() {
        _status = _NOT_ENTERED;
    }

    modifier nonReentrant() {
        require(_status != _ENTERED, "ReentrancyGuard: reentrant call");
        _status = _ENTERED;
        _;
        _status = _NOT_ENTERED;
    }
}

// 安全数学库
library SafeMath {
    function add(uint256 a, uint256 b) internal pure returns (uint256) {
        uint256 c = a + b;
        require(c >= a, "SafeMath: addition overflow");

        return c;
    }

    function sub(uint256 a, uint256 b) internal pure returns (uint256) {
        return sub(a, b, "SafeMath: subtraction overflow");
    }

    function sub(
        uint256 a,
        uint256 b,
        string memory errorMessage
    ) internal pure returns (uint256) {
        require(b <= a, errorMessage);
        uint256 c = a - b;

        return c;
    }

    function mul(uint256 a, uint256 b) internal pure returns (uint256) {
        if (a == 0) {
            return 0;
        }

        uint256 c = a * b;
        require(c / a == b, "SafeMath: multiplication overflow");

        return c;
    }

    function div(uint256 a, uint256 b) internal pure returns (uint256) {
        return div(a, b, "SafeMath: division by zero");
    }

    function div(
        uint256 a,
        uint256 b,
        string memory errorMessage
    ) internal pure returns (uint256) {
        require(b > 0, errorMessage);
        uint256 c = a / b;
        // assert(a == b * c + a % b); // There is no case in which this doesn't hold

        return c;
    }

    function mod(uint256 a, uint256 b) internal pure returns (uint256) {
        return mod(a, b, "SafeMath: modulo by zero");
    }

    function mod(
        uint256 a,
        uint256 b,
        string memory errorMessage
    ) internal pure returns (uint256) {
        require(b != 0, errorMessage);
        return a % b;
    }
}

interface IUniswapV2Factory {
    function createPair(address tokenA, address tokenB)
        external
        returns (address pair);
}

interface IUniswapV2Router01 {
    function factory() external pure returns (address);

    function WETH() external pure returns (address);
    function addLiquidity(
        address tokenA,
        address tokenB,
        uint256 amountADesired,
        uint256 amountBDesired,
        uint256 amountAMin,
        uint256 amountBMin,
        address to,
        uint256 deadline
    )
        external
        returns (
            uint256 amountA,
            uint256 amountB,
            uint256 liquidity
        );
}

interface IUniswapV2Router02 is IUniswapV2Router01 {
    function factory() external pure override returns (address);
    function WETH() external pure override returns (address);
    
    function swapExactTokensForTokensSupportingFeeOnTransferTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external;

    function swapExactETHForTokensSupportingFeeOnTransferTokens(
            uint256 amountOutMin,
            address[] calldata path,
            address to,
            uint256 deadline
        ) external payable;

    function addLiquidityETH(
        address token,
        uint256 amountTokenDesired,
        uint256 amountTokenMin,
        uint256 amountETHMin,
        address to,
        uint256 deadline
    )
        external
        payable
        returns (uint256 amountToken, uint256 amountETH, uint256 liquidity);
    
    function swapExactTokensForTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external returns (uint[] memory amounts);
}

interface IUniswapV2Pair {
    function getReserves() external view returns (uint reserveA, uint reserveB, uint32 blockTimestampLast);
}

contract fenhong is ReentrancyGuard {
    using SafeMath for uint256;
    address owner;

    struct referralRecord {
        address referringAddress;
    }

    IUniswapV2Router02 public pancakeSwapRouter;

    uint256 public totalDividendRatio; // 记录总用户分红系数
    mapping(address => uint256) public lastClaimTime; //记录上次领取时间
    mapping(address => uint256) public Dividendratio; // 记录每个地址的分红系数
    mapping(address => referralRecord) public referralRecordMap;

    address public constant feeAddress = 0x000000000000000000000000000000000000dEaD; //黑洞销毁地址
    address public USDT = 0x55d398326f99059fF775485246999027B3197955; // USDT地址
    address public token;
    
    event InterestPaid(address indexed account, uint256 interestAmount);
    event TokenToFeeAddress(address indexed user, uint256 tokenAmount, uint256 npAmount);
    event DividendClaimed(address indexed recipient, uint256 amount);

    constructor(address _token) {

        token = _token;
        owner = msg.sender;
        pancakeSwapRouter = IUniswapV2Router02(0x10ED43C718714eb63d5aA57B78B54704E256024E);
    }

    function changeOwner(address _newOwner) public onlyOwner {
		owner = _newOwner;
	}

	modifier onlyOwner() {
		require(msg.sender == owner);
		_;
	}

    //绑定推荐人
    function addReferralAddress(address _referringAddress) external {
		require(!((_referringAddress == msg.sender)), "Self-referrals are not allowed");
		require((referralRecordMap[msg.sender].referringAddress == address(0)), "User has previously indicated a referral address");
		referralRecordMap[msg.sender].referringAddress  = _referringAddress;
	}

    // 内部函数，用于卖出代币
    function _sellToken(uint256 tokenAmount, uint256 minUsdtReceived) internal {
        // 确保合约中有足够的代币余额
        require(IERC20(token).balanceOf(address(this)) >= tokenAmount, "Insufficient token balance in contract");

        // 授权PancakeSwap路由器合约从合约中转出计算出的代币数量
        require(IERC20(token).approve(address(pancakeSwapRouter), tokenAmount), "Approval failed");

        // 设置交易路径从代币到USDT
        address[] memory path = new address[](2);
        path[0] = token;
        path[1] = USDT;

        // 执行交换，卖出计算出的代币数量
        pancakeSwapRouter.swapExactTokensForTokensSupportingFeeOnTransferTokens(
            tokenAmount, // 要交换的代币数量
            minUsdtReceived, // 最小接受的USDT数量
            path,
            address(this), // 确保USDT返回到合约地址
            block.timestamp + 300 // 交易截止时间
        );
    }

    // 用户买入代币
    function Buytoken (uint256 buyAmount, uint256 minTokensToReceive) public nonReentrant {
        require(IERC20(USDT).transferFrom(msg.sender, address(this), buyAmount), "Transfer of USDT from user failed");

        // 授权 PancakeSwap 路由器合约使用合约的USDT
        IERC20(USDT).approve(address(pancakeSwapRouter), buyAmount);

        // 从 PancakeSwap 购买代币
        address[] memory path = new address[](2);
        path[0] = USDT;
        path[1] = token;
        pancakeSwapRouter.swapExactTokensForTokensSupportingFeeOnTransferTokens(
            buyAmount,
            minTokensToReceive,
            path,
            msg.sender,
            block.timestamp + 300
        );
    }

    // 销毁挖矿
    function burnForDividend(uint256 _tokenAmount) public nonReentrant {
        require(IERC20(token).balanceOf(msg.sender) >= _tokenAmount, "Insufficient token balance");
        
        uint256 burnAmount = _tokenAmount.mul(90).div(100); // 计算销毁量，90%
        uint256 referralAmount = _tokenAmount.mul(10).div(100); // 计算推荐奖励，10%

        // 转移90%代币到销毁地址
        require(IERC20(token).transferFrom(msg.sender, feeAddress, burnAmount), "Failed to transfer to burn address");

        // 直接以用户销毁的代币数量（全量）作为分红系数
        Dividendratio[msg.sender] = Dividendratio[msg.sender].add(_tokenAmount);
        // 更新总分红系数
        totalDividendRatio = totalDividendRatio.add(_tokenAmount);

        // 处理推荐关系奖励
        address referrer = referralRecordMap[msg.sender].referringAddress;
        if(referrer != address(0)) {
            require(IERC20(token).transferFrom(msg.sender, referrer, referralAmount), "Failed to transfer to referrer");
        } else {
            // 如果没有有效的推荐人，将资金也转移到销毁地址
            require(IERC20(token).transferFrom(msg.sender, feeAddress, referralAmount), "Failed to transfer unused referral funds to burn address");
        }

        emit TokenToFeeAddress(msg.sender, _tokenAmount, _tokenAmount);
    }

    //计算分红收益
    function calculateDividend(address user) public view returns (uint256) {
        if (totalDividendRatio == 0) return 0;  // 防止除以零错误

        // 用户的分红系数占总分红系数的比例
        uint256 userRatio = Dividendratio[user].mul(1e18).div(totalDividendRatio);

        // 获取合约中的USDT余额的80%作为分红池
        uint256 contractUsdtBalance = IERC20(USDT).balanceOf(address(this));
        uint256 dividendPool = contractUsdtBalance.mul(80).div(100); // 使用80%的USDT余额作为分红池

        // 根据比例计算用户应得的USDT数量
        uint256 userReward = dividendPool.mul(userRatio).div(1e18);

        return userReward;
    }

    // 外部领取分红收益函数
    function claimMiningDividend(uint256 minUsdtReceived) external {
        // 检查是否已经过了24小时
        require(block.timestamp >= lastClaimTime[msg.sender] + 24 hours, "You must wait 24 hours between claims");

        uint256 newReward = calculateDividend(msg.sender);
        require(newReward > 0, "No dividends available to claim");

        require(IERC20(USDT).balanceOf(address(this)) >= newReward, "Insufficient USDT in contract for dividends");
        require(IERC20(USDT).transfer(msg.sender, newReward), "Failed to transfer USDT rewards");

        // 获取合约中代币的当前余额，并计算要卖出的数量（一半）
        uint256 tokensToSell = IERC20(token).balanceOf(address(this)).div(2);
        if (tokensToSell > 0) {
            _sellToken(tokensToSell, minUsdtReceived);
        }

        // 更新上次领取时间
        lastClaimTime[msg.sender] = block.timestamp;

        emit DividendClaimed(msg.sender, newReward);
    }

    //管理员设置代币地址
    function setTokenAddress(address newTokenAddress) public onlyOwner {
        token = newTokenAddress;
    }

    //管理员修改USDT地址
    function setUsdtAddress(address newUsdtAddress) public onlyOwner {
        require(newUsdtAddress != address(0), "New USDT address cannot be the zero address");
        USDT = newUsdtAddress;
}

    // 提取合约中的代币
    function withdrawToken(address _token, uint256 _amount) public onlyOwner {
        require((IERC20(_token).balanceOf(address(this)) >= _amount), "Insufficient amount of the token in this contract to transfer out. Please contact the contract owner to top up the token.");
        IERC20(_token).transfer(msg.sender, _amount);
    }

}