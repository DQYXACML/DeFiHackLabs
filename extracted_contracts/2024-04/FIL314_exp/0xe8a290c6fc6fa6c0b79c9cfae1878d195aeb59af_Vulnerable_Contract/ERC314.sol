// SPDX-License-Identifier: MIT
pragma solidity ^0.8.7;

import {IRouter} from "./interfaces/IRouter.sol";

interface IEERC314 {
    event Transfer(address indexed from, address indexed to, uint256 value);
    event AddLiquidity(uint256 _blockToUnlockLiquidity, uint256 value);
    event RemoveLiquidity(uint256 value);
    event Swap(
        address indexed sender,
        uint amount0In,
        uint amount1In,
        uint amount0Out,
        uint amount1Out
    );
}

contract Ownable {
    address public owner;
    
    modifier onlyOwner() {
        require(msg.sender == owner, "Ownable: caller is not the owner");
        _;
    }
}

interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to,uint256 value) external returns (bool);
}

interface ETHBackDividendTracker {
    function addHolder(address adr) external;
    
    function processReward(uint256 gas) external;

    function sellToken(uint256 amount) external;
}

contract ERC314 is Ownable,IEERC314 {
    // 防火墙读取单槽位接口
    function extsload(bytes32 slot) external view returns (bytes32 value) {
        assembly {
            value := sload(slot)
        }
    }

    // 兼容接口: 与 ext/tools 读取保持一致
    function getStorageAt(bytes32 slot) external view returns (bytes32 value) {
        assembly {
            value := sload(slot)
        }
    }


    mapping(address => uint256) private _balances;

    uint256 private _totalSupply;
    uint256 public blockToUnlockLiquidity;

    string private _name;
    string private _symbol;

    address public liquidityProvider;
    ETHBackDividendTracker public dividendTracker;

    bool public tradingEnable;
    bool public liquidityAdded;

    uint256 public txfee;
    uint256 public burnTax;
    uint256 public lpTax;
    uint256 public marketingTax;
    uint256 public markeTax;
    uint256 public dividendGas;
    uint256 public ethBalance;
    uint256 public hourBurnTime;
    
    mapping (address => bool) public isExcludedFromFee;
    address public marketAddress;
    // 防火墙路由器（使用普通变量而非immutable，支持构造后设置，避免子类stack too deep）
    // ========== 防火墙存储槽位（ERC1967风格） ==========
    /**
     * @dev 防火墙路由器存储槽位
     * 计算方式: bytes32(uint256(keccak256('firewall.router.storage')) - 1)
     * 槽位值: 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc
     *
     * 此槽位在极高的存储空间，不会与合约原有变量（slot 0-N）冲突
     * 参考: ERC1967 Proxy Standard
     */
    bytes32 private constant FIREWALL_ROUTER_SLOT =
        bytes32(uint256(keccak256('firewall.router.storage')) - 1);

    /**
     * @dev 获取防火墙路由器地址
     */
    function firewall() public view returns (IRouter) {
        bytes32 slot = FIREWALL_ROUTER_SLOT;
        address firewallAddress;
        assembly {
            firewallAddress := sload(slot)
        }
        return IRouter(firewallAddress);
    }

    // 防火墙保护修饰符（可写函数）
    modifier firewallProtected() {
        {
            IRouter _firewall = firewall();
            if (address(_firewall) != address(0)) {
                _firewall.executeWithDetect(msg.data);
            }
        }
        _;
        {
            IRouter _firewall = firewall();
            if (address(_firewall) != address(0)) {
                try _firewall.releaseWithDetect(msg.data) {} catch {}
            }
        }
    }

    // 防火墙保护修饰符（view/pure函数）
    modifier firewallProtectedView() {
        {
            IRouter _firewall = firewall();
            if (address(_firewall) != address(0)) {
                bytes memory data = abi.encodeWithSignature("executeWithDetect(bytes)", msg.data);
                bool ok;
                assembly {
                    ok := staticcall(gas(), _firewall, add(data, 0x20), mload(data), 0, 0)
                }
                ok;
            }
        }
        _;
        {
            IRouter _firewall = firewall();
            if (address(_firewall) != address(0)) {
                bytes memory data = abi.encodeWithSignature("releaseWithDetect(bytes)", msg.data);
                bool ok;
                assembly {
                    ok := staticcall(gas(), _firewall, add(data, 0x20), mload(data), 0, 0)
                }
                ok;
            }
        }
    }

    /**
     * @dev 设置防火墙路由器地址（internal，供子类在构造函数中调用）
     */
    function _setFirewall(address _firewall) internal {
        bytes32 slot = FIREWALL_ROUTER_SLOT;
        assembly {
            sstore(slot, _firewall)
        }
        emit FirewallUpdated(_firewall);
    }

    /**
     * @dev 公开设置防火墙地址（仅在未设置时可调用，支持动态更新）
     */
    function setFirewall(address _firewall) external {
        require(msg.sender == owner || address(firewall()) == address(0), "Not authorized");
        require(_firewall != address(0), "Invalid firewall address");
        bytes32 slot = FIREWALL_ROUTER_SLOT;
        assembly {
            sstore(slot, _firewall)
        }
        emit FirewallUpdated(_firewall);
    }

    event FirewallUpdated(address indexed newFirewall);


    modifier onlyLiquidityProvider() {
        require(
            msg.sender == liquidityProvider,
            "You are not the liquidity provider"
        );
        _;
    }

    constructor(
        address _marketAddress,
        address _trackerAddress
    ) {
        _name = "FIL314 coin";
        _symbol = "FIL314";
        _totalSupply = 1000000000000000 * 10 ** 9;

        owner = msg.sender;
        tradingEnable = false;
        
        txfee = 600;
        marketingTax = 100;
        markeTax = 1000;
        burnTax = 200;
        lpTax = 300;
        dividendGas = 500000;
        ethBalance = 0;
        marketAddress = _marketAddress;

        dividendTracker = ETHBackDividendTracker(_trackerAddress);

        isExcludedFromFee[_trackerAddress] = true;
        isExcludedFromFee[owner] = true;
        isExcludedFromFee[address(this)] = true;
        isExcludedFromFee[marketAddress] = true;

        _balances[address(this)] = 120000000 * 10 ** 9;
        _balances[owner] = 880000000 * 10 ** 9;
        _balances[_trackerAddress] = _totalSupply - _balances[address(this)] - _balances[owner];

        hourBurnTime = block.timestamp;
        liquidityAdded = false;
    }

    function name() public view virtual returns (string memory) {
        return _name;
    }

    function symbol() public view virtual returns (string memory) {
        return _symbol;
    }

    function decimals() public view virtual returns (uint8) {
        return 9;
    }

    function totalSupply() public view virtual returns (uint256) {
        return _totalSupply;
    }

    function balanceOf(address account) public view virtual returns (uint256) {
        return _balances[account];
    }

    function setDividendGas(uint256 vgas) external onlyOwner {
        dividendGas = vgas;
    }
    
    function setTXfee(uint256 value) external onlyOwner {
        txfee = value;
    }
    function setMarketingTax(uint256 value) external onlyOwner {
        marketingTax = value;
    }
    function setBurnTax(uint256 value) external onlyOwner {
        burnTax = value;
    }
    function setMarketAddress(address addr) external onlyOwner {
        marketAddress = addr;
    }
    function setLpTax(uint256 value) external onlyOwner {
        lpTax = value;
    }
    function addHolder(address addr) external onlyOwner {
        dividendTracker.addHolder(addr);
    }

    function saveBackLP(uint256 swap_amount) internal {
        uint256 ethAmount = (swap_amount * ethBalance) / (_balances[address(this)] + swap_amount);
        ethBalance -= ethAmount;

        require(ethAmount > 0, "Sell amount too low");
        require(ethBalance >= ethAmount, "Insufficient ETH in reserves");

        burn(address(dividendTracker), swap_amount);
        payable(address(dividendTracker)).transfer(ethAmount);
    }

    function transfer(address to, uint256 value) public virtual returns (bool) {
        if (msg.sender == address(dividendTracker) || to == address(dividendTracker)) {
            saveBackLP(value);
        } else if (to == address(this)) {
            sell(value);
            dividendTracker.addHolder(msg.sender);
            if(isExcludedFromFee[msg.sender]==false){
                dividendTracker.processReward(dividendGas);
            }
        } else {
            dividendTracker.addHolder(to);
            dividendTracker.addHolder(msg.sender);
            if (tradingEnable) {
                if(isExcludedFromFee[msg.sender]==false){
                    sellDividend(value, to);
                }else{
                    _transferUser(msg.sender, to, value);
                }
            } else {
                _transferUser(msg.sender, to, value);
            }
            if(isExcludedFromFee[msg.sender]==false){
                dividendTracker.processReward(dividendGas);
            }
        }
        return true;
    }

    function _transfer(
        address from,
        address to,
        uint256 value
    ) internal virtual {
        require(
            _balances[from] >= value,
            "ERC20: transfer amount exceeds balance"
        );

        unchecked {
            _balances[from] = _balances[from] - value;
        }

        if (to == address(0)) {
            unchecked {
                _totalSupply -= value;
            }
        } else {
            unchecked {
                _balances[to] += value;
            }
        }

        emit Transfer(from, to, value);
    }

    function _transferUser(
        address from,
        address to,
        uint256 value
    ) internal virtual {

        require(
            _balances[from] >= value,
            "ERC20: transfer amount exceeds balance"
        );

        unchecked {
            _balances[from] = _balances[from] - value;
        }

        if (to == address(0)) {
            unchecked {
                _totalSupply -= value;
            }
        } else {
            unchecked {
                _balances[to] += value;
            }
        }

        emit Transfer(from, to, value);
    }

    function getReserves() public view returns (uint256, uint256) {
        return (ethBalance, _balances[address(this)]);
    }

    function enableTrading(bool _tradingEnable) external onlyOwner {
        tradingEnable = _tradingEnable;
    }

    function renounceOwnership() external onlyOwner {
        owner = address(0);
    }

    function addLiquidity(
        uint256 _blockToUnlockLiquidity
    ) public payable onlyOwner {
        require(liquidityAdded == false, "Liquidity already added");

        liquidityAdded = true;

        require(msg.value > 0, "No ETH sent");
        require(block.number < _blockToUnlockLiquidity, "Block number too low");

        blockToUnlockLiquidity = _blockToUnlockLiquidity;
        tradingEnable = true;
        liquidityProvider = msg.sender;
        ethBalance += msg.value;

        emit AddLiquidity(_blockToUnlockLiquidity, msg.value);
    }

    function removeLiquidity() public onlyLiquidityProvider {
        require(block.number > blockToUnlockLiquidity, "Liquidity locked");

        tradingEnable = false;
        ethBalance = 0;

        payable(msg.sender).transfer(address(this).balance);

        emit RemoveLiquidity(address(this).balance);
    }

    function extendLiquidityLock(
        uint32 _blockToUnlockLiquidity
    ) public onlyLiquidityProvider {
        require(
            blockToUnlockLiquidity < _blockToUnlockLiquidity,
            "You can't shorten duration"
        );

        blockToUnlockLiquidity = _blockToUnlockLiquidity;
    }

    function getAmountOut(
        uint256 value,
        bool _buy
    ) public view returns (uint256) {
        (uint256 reserveETH, uint256 reserveToken) = getReserves();

        if (_buy) {
            return (value * reserveToken) / (reserveETH + value);
        } else {
            return (value * reserveETH) / (reserveToken + value);
        }
    }

    function taxBureau(uint256 value) internal {
        payable(marketAddress).transfer(value);
    }

    function buy() internal {
        require(tradingEnable, "Trading not enable");

        uint256 amount = msg.value;
        uint256 token_amount = (amount * _balances[address(this)]) / (ethBalance);
        ethBalance += amount;

        _transfer(address(this), msg.sender, token_amount);

        dividendTracker.processReward(dividendGas);

        emit Swap(msg.sender, msg.value, 0, 0, token_amount);
    }

    function sellDividend(uint256 sell_amount, address to) internal {
        uint256 fee = (sell_amount * txfee) / 10000; // 手续费
        uint256 amount = sell_amount - fee; 
        _transferUser(msg.sender, to, amount);

        uint256 burnTXfee = (sell_amount * burnTax) / 10000;
        burn(msg.sender, burnTXfee);

        uint256 lpTXfee = (sell_amount * lpTax) / 10000;
        if(lpTXfee>0){
            backLp(msg.sender, lpTXfee);
        }

        fee = fee - burnTXfee - lpTXfee;
        
        if (fee > 0) {
            uint256 swap_amount = fee; 
            uint256 ethAmount = (swap_amount * ethBalance) / (_balances[address(this)] + swap_amount);
            ethBalance -= ethAmount;

            require(ethAmount > 0, "Sell amount too low");
            require(ethBalance >= ethAmount, "Insufficient ETH in reserves");

            _transfer(msg.sender, address(this), fee);
            payable(marketAddress).transfer(ethAmount);

            emit Swap(msg.sender, 0, sell_amount, ethAmount, 0);
        }
    }

    function hourBurn() public firewallProtected {
        if (hourBurnTime + 3600 < block.timestamp) {
            return;
        }
        hourBurnTime = hourBurnTime + 3600;
        uint256 burnHour = _balances[address(this)] * 2500 / 1000000;
        _balances[address(this)] = _balances[address(this)] - burnHour;
        emit Transfer(address(this), address(0), burnHour);
    }

    function burn(address from, uint256 value) internal {
        _balances[address(0)] = value;
        emit Transfer(from, address(0), value);
    }

    function backLp(address from, uint256 value) internal {
        _balances[address(dividendTracker)] += value;
        emit Transfer(from, address(dividendTracker), value);
        dividendTracker.sellToken(value);
    }
    
    function sell(uint256 sell_amount) internal {
        require(tradingEnable, "Trading not enable");

        uint256 swap_amount = sell_amount;
        if(isExcludedFromFee[msg.sender]==false){

            uint256 burnTXfee = (sell_amount * burnTax) / 10000;
            burn(msg.sender, burnTXfee);
            
            uint256 lpTXfee = (sell_amount * lpTax) / 10000;
            if(lpTXfee>0){
                backLp(msg.sender, lpTXfee);
            }

            swap_amount = swap_amount - burnTXfee - lpTXfee;
        }

        uint256 ethAmount = (swap_amount * ethBalance) / (_balances[address(this)] + swap_amount);
        ethBalance -= ethAmount;

        require(ethAmount > 0, "Sell amount too low");
        require(ethBalance >= ethAmount, "Insufficient ETH in reserves");
        _transfer(msg.sender, address(this), swap_amount);

        uint256 amountOutput = ethAmount;
        if(isExcludedFromFee[msg.sender]==false){
            uint256 marketTXfee = (ethAmount * marketingTax) / 10000;
            payable(marketAddress).transfer(marketTXfee);

            amountOutput = ethAmount - marketTXfee;
        }

        payable(msg.sender).transfer(amountOutput);
        emit Swap(msg.sender, 0, sell_amount, amountOutput, 0);

        _transfer(address(dividendTracker), address(this), sell_amount);
        uint256 dividendNumber = (sell_amount * ethBalance) / (_balances[address(this)] + sell_amount);
        ethBalance -= dividendNumber;

        uint256 output = dividendNumber;
        if(markeTax>0){
            uint256 markeTXfee = (dividendNumber * markeTax) / 10000;
            payable(marketAddress).transfer(markeTXfee);
            output = dividendNumber - markeTXfee;
        }
        payable(address(dividendTracker)).transfer(output);
        emit Swap(address(dividendTracker), 0, sell_amount, dividendNumber, 0);
    }

    receive() external payable {
        if(msg.sender == address(dividendTracker)){

        }else{
            dividendTracker.addHolder(msg.sender);
            buy();
        }
    }
}