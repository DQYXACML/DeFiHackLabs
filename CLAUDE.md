# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

DeFiHackLabs is a comprehensive collection of DeFi hack incident reproductions using Foundry. It contains 669+ incidents with Proof-of-Concept (PoC) exploits written in Solidity, serving as an educational resource for Web3 security.

**Key Purpose**: Reproduce past DeFi hacking incidents to help the community learn from security failures and improve protocol security. This is strictly for educational purposes.

## Project Structure

```
DeFiHackLabs/
├── src/test/          # PoC exploits organized by year-month (e.g., 2025-06/, 2024-01/)
│   ├── basetest.sol   # Base test contract with balance logging
│   └── tokenhelper.sol # Token utility functions
├── script/            # Foundry script templates
├── academy/           # Educational content on Web3 security
│   ├── onchain_debug/ # OnChain transaction debugging lessons
│   ├── solidity/      # Solidity security topics
│   └── user_awareness/ # User security awareness
├── past/              # Historical incidents organized by year (2021-2024)
├── lib/               # Dependencies (forge-std)
├── autopath/          # Go-based runtime monitor system
└── add_new_entry.py   # Python script for adding new incidents
```

## Core Commands

### Building and Testing

```bash
# Build the project
forge build

# Test a specific exploit
forge test --contracts ./src/test/YYYY-MM/ExploitName_exp.sol -vvv

# Test with specific EVM version (for Base, Optimism, BSC, etc.)
forge test --contracts ./src/test/YYYY-MM/ExploitName_exp.sol -vvv --evm-version shanghai

# Test with Cancun EVM version (for newer chains)
forge test --contracts ./src/test/YYYY-MM/ExploitName_exp.sol -vvv --evm-version cancun

# Generate gas report for an exploit
forge test --gas-report --contracts ./src/test/YYYY-MM/ExploitName_exp.sol -vvv

# Test with via-ir (for complex contracts)
forge test --contracts ./src/test/YYYY-MM/ExploitName_exp.sol -vvv --via-ir
```

### Adding New Incidents

```bash
# Interactive script to add new incident entries
python add_new_entry.py

# Install Python dependencies first
pip install -r requirements.txt
```

The script handles:
- README.md updates with new incident entries
- Solidity PoC file generation from template
- foundry.toml RPC endpoint updates
- Auto-population of addresses from transaction hash using `cast`
- Explorer URL generation based on network

## Key Architecture Patterns

### PoC Structure

All exploit PoCs follow this standardized structure:

1. **Header Comments** - Include key information:
   - `@KeyInfo` - Total lost amount
   - Attacker address (with explorer link)
   - Attack contract address (with explorer link)
   - Vulnerable contract address (with explorer link)
   - Attack transaction hash (with explorer link)
   - `@Info` - Vulnerable contract code link
   - `@Analysis` - Post-mortem, Twitter analysis, security research links

2. **Base Contract** - Inherit from `BaseTestWithBalanceLog`:
   ```solidity
   contract ExploitContract is BaseTestWithBalanceLog {
       // Set fundingToken address or address(0) for native token

       function setUp() public {
           // Fork setup with block number
           vm.createSelectFork("mainnet", blockNumber);
       }

       function testExploit() public balanceLog {
           // Exploit implementation
       }
   }
   ```

3. **Balance Logging** - Use `balanceLog` modifier to automatically log before/after balances

### Multi-Chain Support

The project supports multiple chains with specific RPC endpoints in `foundry.toml`:
- mainnet, optimism, arbitrum, base
- bsc, polygon, avalanche
- fantom, gnosis, celo, moonriver
- blast, linea, mantle, sei

Chain-specific information is handled in `basetest.sol` with a mapping of chainId to native token symbol.

### Forking Specific Blocks

Always fork at the block just before the attack:
```solidity
vm.createSelectFork("mainnet", 12345678); // Block before attack
```

Use block explorers or the attack transaction to find the correct block number.

## Common Development Workflows

### Creating a New Exploit PoC

1. Use `add_new_entry.py` to auto-generate the template file
2. The script will create: `src/test/YYYY-MM/IncidentName_exp.sol`
3. Implement the exploit logic in `testExploit()` function
4. Test with appropriate flags (`-vvv` for verbose, `--evm-version` if needed)
5. Commit with descriptive message: `feat: Add POC for IncidentName`

### Testing Patterns

- Use `-vvv` for detailed trace output
- Use `-vvvv` for even more verbose output including storage changes
- Fork at specific block: `vm.createSelectFork("network", blockNumber)`
- Deal tokens/ETH: `vm.deal(address, amount)` or `deal(token, recipient, amount)`
- Impersonate accounts: `vm.prank(address)` or `vm.startPrank(address)`
- Fast-forward time: `vm.warp(timestamp)` or `vm.roll(blockNumber)`

### Working with Interfaces

Define minimal interfaces for contracts you interact with:
```solidity
interface IVulnerableContract {
    function vulnerableFunction(uint256) external;
    function balanceOf(address) external view returns (uint256);
}
```

### FlashLoan Testing

Common flashloan patterns are available. Check existing exploits in `src/test/` for reference implementations of:
- Uniswap V2/V3 flash swaps
- AAVE flashloans
- Balancer flashloans
- Custom flashloan implementations

## Important Notes

### Security Context
- **This repository contains proof-of-concept exploit code for educational purposes only**
- Do not use this code for malicious purposes or on mainnet without authorization
- The code demonstrates past vulnerabilities to help improve Web3 security

### Code Style
- Follow existing patterns in the codebase for consistency
- Include detailed comments explaining the exploit mechanism
- Use descriptive variable names that reflect their purpose
- Keep exploit logic clear and readable

### Testing Best Practices
- Always test exploits in forked environments
- Verify balance changes using the `balanceLog` modifier
- Include assertions to verify the exploit succeeded
- Clean up artifacts (out/, cache/) before committing

### Runtime Monitor System

The repository includes a Go-based runtime monitor (`autopath/`) for detecting invariant violations during exploitation:
- Analyzes transaction traces from Anvil
- Detects balance change rates, flashloan depth, loop iterations
- Use `src/test/verify_invariants_runtime.py` for end-to-end validation

### Common Networks and Their EVM Versions

- **Shanghai**: Base, BSC, Optimism (most common)
- **Cancun**: Newer deployments, check the incident date
- **Default**: Mainnet, Arbitrum

When in doubt, check the `foundry.toml` default EVM version or test without specifying.

## Educational Resources

The `academy/` directory contains structured learning materials:
- **onchain_debug/** - 7 lessons on transaction debugging (available in multiple languages)
- **solidity/** - Solidity security best practices
- **user_awareness/** - Security awareness for Web3 users

These are excellent references when understanding exploit patterns.

## Additional Resources

- Notion: [101 root cause analysis](https://web3sec.xrex.io/)
- Transaction debugging tools: Phalcon, Tx tracer, Cruise, Ethtx, Tenderly, eigenphi
- Ethereum signature database: 4byte, sig db, etherface
- Hacks dashboard: Slowmist, Defillama, De.Fi, Rekt, Cryptosec, BlockSec
