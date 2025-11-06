# Via-IR 编译配置说明

## 问题背景

由于 Solidity 编译器的栈深度限制，部分复杂的 PoC 合约需要使用 `via-ir` (Yul IR) 编译模式。但是，某些合约在 via-ir 模式下会遇到 Yul 优化器的栈深度问题。因此，本项目采用**双 Profile 策略**。

## 配置说明

### Default Profile（默认）
- **via_ir**: false（关闭）
- **用途**: 编译大部分 PoC 文件
- **使用方式**: `forge build` 或 `forge test`

### Via-IR Profile
- **via_ir**: true（开启）
- **用途**: 编译有 Solidity "stack too deep" 错误的文件
- **使用方式**: `FOUNDRY_PROFILE=via-ir forge build --contracts <file>`

## 需要使用 Via-IR Profile 的文件

以下文件**必须**使用 via-ir profile 编译，否则会遇到 "Stack too deep" 错误：

### 2024-11
- `src/test/2024-11/proxy_b7e1_exp.sol`
  ```bash
  FOUNDRY_PROFILE=via-ir forge test --contracts ./src/test/2024-11/proxy_b7e1_exp.sol -vvv
  ```

### 2025-05
- `src/test/2025-05/Corkprotocol_exp.sol`
  ```bash
  FOUNDRY_PROFILE=via-ir forge test --contracts ./src/test/2025-05/Corkprotocol_exp.sol -vvv
  ```

## 不能使用 Via-IR Profile 的文件

以下文件使用 via-ir 会遇到 "Yul exception" 错误，**必须**使用 default profile：

### 2023-07
- `src/test/2023-07/ArcadiaFi_exp.sol`
  ```bash
  forge test --contracts ./src/test/2023-07/ArcadiaFi_exp.sol -vvv
  ```

## 添加新的 PoC 文件

1. **默认使用 default profile** 进行编译和测试
2. **如果遇到 "Stack too deep" 错误**:
   - 尝试使用 `FOUNDRY_PROFILE=via-ir` 编译
   - 如果成功，将文件添加到本文档的"需要使用 Via-IR Profile 的文件"列表
3. **如果 via-ir 模式遇到 "Yul exception" 错误**:
   - 使用 default profile
   - 需要通过代码重构来减少局部变量（将文件添加到"不能使用 Via-IR Profile 的文件"列表）

## 错误识别

### Solidity Stack Too Deep（需要 via-ir）
```
Error: Compiler error (/solidity/libsolidity/codegen/LValue.cpp:50):
Stack too deep. Try compiling with `--via-ir`
```
**解决方案**: 使用 `FOUNDRY_PROFILE=via-ir`

### Yul Exception（不能用 via-ir）
```
Error: Yul exception:Cannot swap Variable expr_3 with Variable _61:
too deep in the stack by 1 slots
```
**解决方案**: 使用 default profile（不使用 via-ir）

## 全项目编译

由于文件需求不同，**无法**一次性编译所有文件。建议：

1. 使用 default profile 编译大部分文件:
   ```bash
   forge build
   ```

2. 对需要 via-ir 的文件单独编译:
   ```bash
   FOUNDRY_PROFILE=via-ir forge build --contracts src/test/2024-11/proxy_b7e1_exp.sol
   FOUNDRY_PROFILE=via-ir forge build --contracts src/test/2025-05/Corkprotocol_exp.sol
   ```

## 更新记录

- 2025-10-30: 初始化文档，记录已知的 via-ir 需求文件
