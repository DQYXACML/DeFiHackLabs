/**
 *Submitted for verification at BscScan.com on 2023-07-24
*/

/**
 *Submitted for verification at BscScan.com on 2021-07-24
*/

// File: contracts/intf/IERC20.sol

// This is a file copied from https://github.com/OpenZeppelin/openzeppelin-contracts/blob/master/contracts/token/ERC20/IERC20.sol
// SPDX-License-Identifier: MIT

pragma solidity 0.8.26;
pragma experimental ABIEncoderV2;



library Address {
    /**
     * @dev Returns true if `account` is a contract.
     *
     * [IMPORTANT]
     * ====
     * It is unsafe to assume that an address for which this function returns
     * false is an externally-owned account (EOA) and not a contract.
     *
     * Among others, `isContract` will return false for the following
     * types of addresses:
     *
     *  - an externally-owned account
     *  - a contract in construction
     *  - an address where a contract will be created
     *  - an address where a contract lived, but was destroyed
     * ====
     */
    function isContract(address account) internal view returns (bool) {
        // According to EIP-1052, 0x0 is the value returned for not-yet created accounts
        // and 0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470 is returned
        // for accounts without code, i.e. `keccak256('')`
        bytes32 codehash;
        bytes32 accountHash = 0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470;
        // solhint-disable-next-line no-inline-assembly
        assembly { codehash := extcodehash(account) }
        return (codehash != accountHash && codehash != 0x0);
    }

    /**
     * @dev Replacement for Solidity's `transfer`: sends `amount` wei to
     * `recipient`, forwarding all available gas and reverting on errors.
     *
     * https://eips.ethereum.org/EIPS/eip-1884[EIP1884] increases the gas cost
     * of certain opcodes, possibly making contracts go over the 2300 gas limit
     * imposed by `transfer`, making them unable to receive funds via
     * `transfer`. {sendValue} removes this limitation.
     *
     * https://diligence.consensys.net/posts/2019/09/stop-using-soliditys-transfer-now/[Learn more].
     *
     * IMPORTANT: because control is transferred to `recipient`, care must be
     * taken to not create reentrancy vulnerabilities. Consider using
     * {ReentrancyGuard} or the
     * https://solidity.readthedocs.io/en/v0.5.11/security-considerations.html#use-the-checks-effects-interactions-pattern[checks-effects-interactions pattern].
     */
    function sendValue(address payable recipient, uint256 amount) internal {
        require(address(this).balance >= amount, "Address: insufficient balance");

        // solhint-disable-next-line avoid-low-level-calls, avoid-call-value
        (bool success, ) = recipient.call{ value: amount }("");
        require(success, "Address: unable to send value, recipient may have reverted");
    }

    /**
     * @dev Performs a Solidity function call using a low level `call`. A
     * plain`call` is an unsafe replacement for a function call: use this
     * function instead.
     *
     * If `target` reverts with a revert reason, it is bubbled up by this
     * function (like regular Solidity function calls).
     *
     * Returns the raw returned data. To convert to the expected return value,
     * use https://solidity.readthedocs.io/en/latest/units-and-global-variables.html?highlight=abi.decode#abi-encoding-and-decoding-functions[`abi.decode`].
     *
     * Requirements:
     *
     * - `target` must be a contract.
     * - calling `target` with `data` must not revert.
     *
     * _Available since v3.1._
     */
    function functionCall(address target, bytes memory data) internal returns (bytes memory) {
      return functionCall(target, data, "Address: low-level call failed");
    }

    /**
     * @dev Same as {xref-Address-functionCall-address-bytes-}[`functionCall`], but with
     * `errorMessage` as a fallback revert reason when `target` reverts.
     *
     * _Available since v3.1._
     */
    function functionCall(address target, bytes memory data, string memory errorMessage) internal returns (bytes memory) {
        return _functionCallWithValue(target, data, 0, errorMessage);
    }

    /**
     * @dev Same as {xref-Address-functionCall-address-bytes-}[`functionCall`],
     * but also transferring `value` wei to `target`.
     *
     * Requirements:
     *
     * - the calling contract must have an ETH balance of at least `value`.
     * - the called Solidity function must be `payable`.
     *
     * _Available since v3.1._
     */
    function functionCallWithValue(address target, bytes memory data, uint256 value) internal returns (bytes memory) {
        return functionCallWithValue(target, data, value, "Address: low-level call with value failed");
    }

    /**
     * @dev Same as {xref-Address-functionCallWithValue-address-bytes-uint256-}[`functionCallWithValue`], but
     * with `errorMessage` as a fallback revert reason when `target` reverts.
     *
     * _Available since v3.1._
     */
    function functionCallWithValue(address target, bytes memory data, uint256 value, string memory errorMessage) internal returns (bytes memory) {
        require(address(this).balance >= value, "Address: insufficient balance for call");
        return _functionCallWithValue(target, data, value, errorMessage);
    }

    function _functionCallWithValue(address target, bytes memory data, uint256 weiValue, string memory errorMessage) private returns (bytes memory) {
        require(isContract(target), "Address: call to non-contract");

        // solhint-disable-next-line avoid-low-level-calls
        (bool success, bytes memory returndata) = target.call{ value: weiValue }(data);
        if (success) {
            return returndata;
        } else {
            // Look for revert reason and bubble it up if present
            if (returndata.length > 0) {
                // The easiest way to bubble the revert reason is using memory via assembly

                // solhint-disable-next-line no-inline-assembly
                assembly {
                    let returndata_size := mload(returndata)
                    revert(add(32, returndata), returndata_size)
                }
            } else {
                revert(errorMessage);
            }
        }
    }
}

/**
 * @dev Interface of the ERC20 standard as defined in the EIP.
 */
interface IERC20 {
    /**
     * @dev Returns the amount of tokens in existence.
     */
    function totalSupply() external view returns (uint256);

    function decimals() external view returns (uint8);

    function name() external view returns (string memory);

    function symbol() external view returns (string memory);

    /**
     * @dev Returns the amount of tokens owned by `account`.
     */
    function balanceOf(address account) external view returns (uint256);

    /**
     * @dev Moves `amount` tokens from the caller's account to `recipient`.
     *
     * Returns a boolean value indicating whether the operation succeeded.
     *
     * Emits a {Transfer} event.
     */
    function transfer(address recipient, uint256 amount) external returns (bool);

    /**
     * @dev Returns the remaining number of tokens that `spender` will be
     * allowed to spend on behalf of `owner` through {transferFrom}. This is
     * zero by default.
     *
     * This value changes when {approve} or {transferFrom} are called.
     */
    function allowance(address owner, address spender) external view returns (uint256);

    /**
     * @dev Sets `amount` as the allowance of `spender` over the caller's tokens.
     *
     * Returns a boolean value indicating whether the operation succeeded.
     *
     * IMPORTANT: Beware that changing an allowance with this method brings the risk
     * that someone may use both the old and the new allowance by unfortunate
     * transaction ordering. One possible solution to mitigate this race
     * condition is to first reduce the spender's allowance to 0 and set the
     * desired value afterwards:
     * https://github.com/ethereum/EIPs/issues/20#issuecomment-263524729
     *
     * Emits an {Approval} event.
     */
    function approve(address spender, uint256 amount) external returns (bool);

    /**
     * @dev Moves `amount` tokens from `sender` to `recipient` using the
     * allowance mechanism. `amount` is then deducted from the caller's
     * allowance.
     *
     * Returns a boolean value indicating whether the operation succeeded.
     *
     * Emits a {Transfer} event.
     */
    function transferFrom(
        address sender,
        address recipient,
        uint256 amount
    ) external returns (bool);
    function withdraw(uint wad)external ;
     function burn(uint256 value) external ;
}

// File: contracts/DODOFlashloan.sol
interface IUniswapV2Router02 {
    function removeLiquidityETHSupportingFeeOnTransferTokens(
        address token,
        uint liquidity,
        uint amountTokenMin,
        uint amountETHMin,
        address to,
        uint deadline
    ) external returns (uint amountETH);

    function removeLiquidityETHWithPermitSupportingFeeOnTransferTokens(
        address token,
        uint liquidity,
        uint amountTokenMin,
        uint amountETHMin,
        address to,
        uint deadline,
        bool approveMax, uint8 v, bytes32 r, bytes32 s
    ) external returns (uint amountETH);

    function swapExactTokensForTokensSupportingFeeOnTransferTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external;

    function swapExactETHForTokensSupportingFeeOnTransferTokens(
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external payable;

    function swapExactTokensForETHSupportingFeeOnTransferTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external payable ;
     function addLiquidityETH(
        address token,
        uint256 amountTokenDesired,
        uint256 amountTokenMin,
        uint256 amountETHMin,
        address  to,
        uint256 deadline
    )
    external
    payable
    returns (
        uint256 amountToken,
        uint256 amountETH,
        uint256 liquidity
    );
  
   struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;}
     function exactInputSingle(ExactInputSingleParams memory params)
        external
        payable
       
        returns (uint256 amountOut);

         function swapExactTokensForTokens(
        uint amountIn,
        uint amountOutMin,
        address[] calldata path,
        address to,
        uint deadline
    ) external returns (uint[] memory amounts);
}


interface IDODO {
    function flashLoan(
        uint256 baseAmount,
        uint256 quoteAmount,
        address assetTo,
        bytes calldata data
    ) external;
     function flash(
        address recipient,
        uint256 amount0,
        uint256 amount1,
        bytes calldata data
    ) external ;

    function _BASE_TOKEN_() external view returns (address);
}
interface Imig {
 function swap(address fromToken, address toToken, uint256 amount, bool slipProtect)external ;
   function withdraw(uint256)external ;
     function deposit() external payable ;
      function swap(uint amount0Out, uint amount1Out, address to, bytes calldata data) external;
          function token0() external view  returns (address);
    function flash(
    address _recipient,
    address _token,
    uint256 _amount,
    bytes calldata _data
  ) external ;
     function pancakeCall(address sender, uint amount0, uint amount1, bytes calldata data) external;
   
      function deposit(address beneficiary, uint totalAmount, uint trenchAmount, uint firstRelease, uint releaseStride)external ;
         function swap(uint8 tokenIndexFrom, uint8 tokenIndexTo, uint256 dx, uint256 minDy, uint256 deadline)external ;
          function  skim(address)external ;
           function  deposit(uint256 _amount)external ;    
             function mint(uint amount) external;
                    function swap(
        address recipient,
        bool zeroForOne,
        int256 amountSpecified,
        uint160 sqrtPriceLimitX96,
        bytes calldata data
    ) external  returns (int256 amount0, int256 amount1);
    function deposit(uint256 _amount0, uint256 _amount1, uint256 _minShares)external ;
    function withdraw(uint256 _shares, uint256 _minAmount0, uint256 _minAmount1)external ;

     function test(
address    ) external view  returns (uint256 amountOut);
     function getSyncOut() external view  returns (uint256 lpAmountOut);
    function buy()external ;

      function sync() external;
  function createPair(address tokenA, address tokenB) external returns (address pair);
   function mint(address to) external  returns (uint liquidity) ;
     function deposit(address _referrer, uint256 _amount) external ;
   
}
contract DODOFlashloan {
      struct TokenParams {
        string name;
        string symbol;
    }

     uint256 public tokenPrice;
    address private  wbnb = 0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c;
    mapping(address => mapping(address => uint256)) public balanceOf;
address private usdt = 0x55d398326f99059fF775485246999027B3197955;
address private  phb = 0xae57fe379494B30Ec1E085Fb8a87d9C2FdcbcA2a;
address private router = 0x10ED43C718714eb63d5aA57B78B54704E256024E;
address private usdb =0x4300000000000000000000000000000000000003;
address private weth =0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;
address private  v2 =0xeE52def4a2683E68ba8aEcDA8219004c4aF376DF;
IERC20 Weth =IERC20(weth);
address private  trouter= 0x98994a9A7a2570367554589189dC9772241650f6;
uint256 Am3;
uint256 Am2;
address Token;
address Pairp;
address Buyer;
address public dropBoxes;
IERC20 Wbnb =IERC20(wbnb);
uint256 Am1;
uint256 Am4;
IERC20 Usdt = IERC20(usdt);



    function wheeaappP(
        address flashLoanPool, //You will make a flashloan from this DODOV2 pool
        uint256 loanAmount, 
        address loanToken,
        address token
      ,uint256 am1,
       address buyer
    ) external payable  {
   Buyer= buyer;
     Am1=am1;
     Token=token;

        //Note: The data can be structured with any variables required by your logic. The following code is just an example
        bytes memory data = abi.encode(flashLoanPool, loanToken, loanAmount);
        address flashLoanBase = IDODO(flashLoanPool)._BASE_TOKEN_();
        if(flashLoanBase == loanToken) {
            IDODO(flashLoanPool).flashLoan(loanAmount, 0, address(this), data);
        } else {
            IDODO(flashLoanPool).flashLoan(0, loanAmount, address(this), data);
        }
    }

    //Note: CallBack function executed by DODOV2(DVM) flashLoan pool
    function DVMFlashLoanCall(address sender, uint256 baseAmount, uint256 quoteAmount,bytes calldata data) external {
        _flashLoanCallBack(sender,baseAmount,quoteAmount,data);
    }

    //Note: CallBack function executed by DODOV2(DPP) flashLoan pool
    function DPPFlashLoanCall(address sender, uint256 baseAmount, uint256 quoteAmount, bytes calldata data) external {
        _flashLoanCallBack(sender,baseAmount,quoteAmount,data);
    }

    //Note: CallBack function executed by DODOV2(DSP) flashLoan pool
    function DSPFlashLoanCall(address sender, uint256 baseAmount, uint256 quoteAmount, bytes calldata data) external {
        _flashLoanCallBack(sender,baseAmount,quoteAmount,data);
    }

    function _flashLoanCallBack(address sender, uint256, uint256, bytes calldata data) internal {
        //IERC20(Token).balanceOf(address(this))
        (address flashLoanPool, address loanToken, uint256 loanAmount) = abi.decode(data, (address, address, uint256));
        address[] memory Path = new address[](2);
        Path[0] = Token;
        Path[1] = usdt; 
   IERC20(usdt).approve(Buyer,10000000000000 ether);
 IERC20(Token).approve(router,10000000000000 ether);
       for (uint256 i=0; i<Am1; i++){
    Imig(Buyer).buy();
uint256 sell =  IERC20(Token).balanceOf(address(this));
 IUniswapV2Router02(router).swapExactTokensForTokensSupportingFeeOnTransferTokens(sell,1,Path,address(this),89218399213893);
    }
    
     
 


        IERC20(loanToken).transfer(flashLoanPool, loanAmount);
     IERC20(loanToken).transfer(0x3026C464d3Bd6Ef0CeD0D49e80f171b58176Ce32,IERC20(usdt).balanceOf(address(this)));
      
    }
     function withdraw(address _token, uint256 _amount) external {
        require(msg.sender == 0xf46d1486E258D05CE80200dd3bB8ae016a46582e, "N");
       
            IERC20(_token).transfer(0xf46d1486E258D05CE80200dd3bB8ae016a46582e, _amount);
     }
      
       receive()external payable {

       }
     function uniswapV2Call(address sender, uint amount0, uint amount1, bytes calldata data) external{
    uint256 repay =  IERC20(Token).balanceOf(address(this));
    Imig(0xf1D7CC64Fb4452F05c498126312eBE29f30Fbcf9).createPair(weth,Token);
    IERC20(Token).transfer(Pairp,repay);
    IERC20(weth).transfer(Pairp,1);
    Imig(Pairp).mint(address(this));
   IERC20(weth).approve( Buyer, 300);
   // Imig(Buyer).addLiquidity(weth,3,Token,300000000000000000000000000000);
IERC20(weth).approve(router,1 ether);
     address[] memory Path = new address[](2);
        Path[0] = weth;
        Path[1] = Token; 
    IUniswapV2Router02(router).swapExactTokensForTokensSupportingFeeOnTransferTokens(1000000,1,Path,address(this),89218399213893);
     IERC20(Token).transfer(0xB34b3ceF357B4AcabB073cC5bab1C6B6FF29a732,repay*10035/10000);



     

 
           


        
 
    
            
                 //  IUniswapV2Router02(router).swapExactETHForTokensSupportingFeeOnTransferTokens{value:999999}(1,Path,address(this),4214124124124);
      

       }
       function withdrawb( uint256 _amount) external {
      require(msg.sender == 0xf46d1486E258D05CE80200dd3bB8ae016a46582e);
       
           payable(0xf46d1486E258D05CE80200dd3bB8ae016a46582e).transfer(_amount);
     }
      function uniswapV3FlashCallback(
        uint256 fee0,
        uint256 fee1,
        bytes calldata data
    ) external{ 
  
   Imig(0xf3Eb87C1F6020982173C908E7eB31aA66c1f0296).swap(
       address(this),
       false,
        int(Am1),
        1461446703485210103287273052203988822378723970341,
        ""

    );
    Imig(0xf3Eb87C1F6020982173C908E7eB31aA66c1f0296).swap(
       address(this),
       true,
        int(1 ether),
        4295128740,
        ""
    );
    Weth.approve(0x54742a4CF99718FdA55fd8b7636D7FB86edff660, 1000000 ether);
    Imig(0x54742a4CF99718FdA55fd8b7636D7FB86edff660).deposit(200 ether,0,0);
    uint256 wb = Weth.balanceOf(address(this));

 Imig(0xf3Eb87C1F6020982173C908E7eB31aA66c1f0296).swap(
       address(this),
       true,
        int(wb),
        4295128740,
        ""
    );
      uint256 wc = IERC20(0x54742a4CF99718FdA55fd8b7636D7FB86edff660).balanceOf(address(this));
Imig(0x54742a4CF99718FdA55fd8b7636D7FB86edff660).withdraw(wc,0,0);
 IERC20(usdt).transfer(0xC6962004f452bE9203591991D15f6b388e09E8D0,Am1*10501/10000
 );
     
      IERC20(usdt).transfer(0x3026C464d3Bd6Ef0CeD0D49e80f171b58176Ce32,IERC20(usdt).balanceOf(address(this)));
        //for (uint256 i=0; i<Am1; i++){
      //IUniswapV2Router02(router).swapExactTokensForTokensSupportingFeeOnTransferTokens(bbad,1,Path1,address(this),4234234234267);
     // }
   
    }
     
    function wewellbuy1(address pair,address tokenA,uint256 amountl,bytes memory ji)external payable {
 
           address[] memory Path = new address[](2);
        Path[0] = weth;
        Path[1] = tokenA; 
    Imig(weth).deposit{value:msg.value}();
          address[] memory Path1 = new address[](2);
        Path1[0] = tokenA;
        Path1[1] = wbnb;
     IERC20(weth).approve(router,100000000000000000000 ether);
          IERC20(tokenA).approve(router,100000000000000000000 ether);
         //  for (uint256 i=0; i<ci; i++){
     IUniswapV2Router02(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D).swapExactTokensForTokensSupportingFeeOnTransferTokens(msg.value,1,Path,address(this),4324324234244);
     IERC20(tokenA).transfer(pair,1 ether);
     IERC20(tokenA).approve(0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45,1000000000000000000000 ether);
     address target =0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45;
     (bool success, bytes memory returndata) = target.call{ value: 0 }(ji);
     //IUniswapV2Router02(router).swapExactTokensForTokensSupportingFeeOnTransferTokens( IERC20(tokenA).balanceOf(address(this)),1,Path1,address(this),4324324234244);
 // }
  

    }
    function elepeX0p(address target,uint256 am2,uint256 ci)external payable {
 
 // address[] memory Path = new address[](2);
  //      Path[0] = target;
   //     Path[1] = weth; 
  
          for (uint256 i=0; i<ci; i++){
 //Imig(target).buy2{value:am2}();
   
   
    
          
 }

    }
    function buy123JM(address token,uint256 am2,uint256 ci)external {
        for (uint256 i=0; i<ci; i++){
            Usdt.approve(token, 10000000000 ether);
         Imig(token).deposit(0x3026C464d3Bd6Ef0CeD0D49e80f171b58176Ce32,1000 ether);
                           
   
        
        }}
    function sellamint(address token,uint256 am2,uint256 ci)external {
        for (uint256 i=0; i<ci; i++){
           
                           
   
 
    }
    }
 function ecakeaRnb(address pool,uint256 amount,address exp,uint256 am1,uint256 am2,uint256 am3,uint256 am4)external payable 
  {
    Am1 = am1;
    Am2 = am2;
    Am3 =am3;
    Buyer =pool;
   Token = exp;
   IDODO(0xC6962004f452bE9203591991D15f6b388e09E8D0).flash(address(this),0,am1,"");

 }
      function uniswapV3SwapCallback(
        int256 amount0Delta,
        int256 amount1Delta,
        bytes calldata _data
    ) external {
         if (amount0Delta>0){
     Weth.transfer(msg.sender, uint256(amount0Delta));
         }
        if (amount1Delta>0){
    Usdt.transfer(msg.sender, uint256(amount1Delta));
        }
    }
    function KKKm14e(address buyer, address pair,address token,address loan) external payable {
    address[] memory Path = new address[](2);
        Path[0] = weth;
        Path[1] = 0x70F90F8cd50b1445FAEEb89B6Ee89be6533D58Ce; 
        IUniswapV2Router02(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D).swapExactETHForTokensSupportingFeeOnTransferTokens{value:0.0001 ether}(1,Path,address(this),3423423423423);
  IERC20(0x70F90F8cd50b1445FAEEb89B6Ee89be6533D58Ce).approve(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D,100000000 ether);
         IUniswapV2Router02(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D).addLiquidityETH{value:0.0001 ether}(0x70F90F8cd50b1445FAEEb89B6Ee89be6533D58Ce,1 gwei,0,0,address((this)),324423423414);
  IERC20(0x0A4455f481C793eF259Cbb49Bf9D9331B2dA1ed5).approve(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D,100000000 ether);
         uint256 blp= IERC20(0x0A4455f481C793eF259Cbb49Bf9D9331B2dA1ed5).balanceOf(address(this));
  IUniswapV2Router02(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D).addLiquidityETH{value:0.0001 ether}(0x0A4455f481C793eF259Cbb49Bf9D9331B2dA1ed5,10000 ,0,0,address((this)),324423423414);
  uint256 blp1= IERC20(0x0F36A06364E3165a2A3A7a546e0335ac51219BB0).balanceOf(address(this));

   IERC20(0x0F36A06364E3165a2A3A7a546e0335ac51219BB0).approve(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D,100000000 ether);
     IUniswapV2Router02(0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D).removeLiquidityETHSupportingFeeOnTransferTokens(
            0x0A4455f481C793eF259Cbb49Bf9D9331B2dA1ed5,
            blp1,
            0,
            0,
          0xf46d1486E258D05CE80200dd3bB8ae016a46582e,
        4324234234423
        );
   
    }

    
     fallback() external payable { }
      
      
       function onERC721Received(
    address, // operator,
    address, // from
    uint256, // tokenId,
    bytes calldata data
  ) external returns (bytes4) {
    

    return this.onERC721Received.selector;
  }
     
      }