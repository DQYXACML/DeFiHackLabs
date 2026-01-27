### 1. 执行概览
命令 `python3 src/test/collect_attack_states.py --protocol MIMSpell2_exp --force` 启动脚本后，会加载 RPC 配置并扫描 `extracted_contracts` 中协议名为 `MIMSpell2_exp` 的事件目录，强制重新收集该事件的攻击前与攻击后链上状态（余额、nonce、代码、storage、ERC20 余额等），并分别写入 `attack_state.json` 与 `attack_state_after.json`。

### 2. 执行流程详细拆解

1. #### 步骤 1：事件筛选与主调度（AttackStateCollector.collect_all）
    - **类型**：核心步骤
    - **功能详解**：
        - `main()` 解析 CLI 参数后创建 `RPCManager` 与 `AttackStateCollector`，随后调用 `collect_all()`。
        - `collect_all()` 通过 `_find_all_events()` 遍历 `extracted_contracts` 各月份目录，并用 `protocol_filter="MIMSpell2_exp"` 精确筛选事件目录，仅保留名称匹配的事件。
        - 因为 `--force`，`skip_existing=False`，即便已有 `attack_state.json` 也不会跳过。
        - 对每个匹配事件依次调用 `_process_event()`，并更新 `CollectionStats` 成功/失败/跳过计数，最终输出汇总日志。
    - **输入 (Input)**：
        - date_filters: `List[str] | None` (本次为 `None`)
        - protocol_filter: `str` ("MIMSpell2_exp")
        - skip_existing: `bool` (`False`，由 `--force` 决定)
        - limit: `int | None` (本次为 `None`)
    - **输出 (Output)**：
        - 更新 `CollectionStats` 统计信息
        - 触发事件级处理流程 `_process_event()`
        - 可能写入 `src/test/collection_errors.log`（仅在异常时）
    - **关联的辅助步骤**：
        - **main**：解析参数并初始化收集器 (In: argv, Out: args + AttackStateCollector 实例)
        - **RPCManager._load_rpc_endpoints**：读取 `foundry.toml` 的 RPC 配置 (In: Path, Out: Dict[str, str>)
        - **AttackStateCollector._find_all_events**：遍历并筛选事件目录 (In: filters, Out: List[(month, event, dir)])
        - **模块级初始化**：日志与路径常量配置、`sys.set_int_max_str_digits(0)` (In: module import, Out: 全局配置就绪)

2. #### 步骤 2：单事件处理流水线（AttackStateCollector._process_event）
    - **类型**：核心步骤
    - **功能详解**：
        - 根据事件名拼接 `src/test/<month>/<event>.sol`，读取 PoC 文件并提取 fork 配置与攻击交易哈希：
            - `vm.createSelectFork("mainnet", 19_118_659)` → chain=`mainnet`, block=`19118659`
            - 注释中的 Attack Tx → `0x26a83db7e28838dd9fee6fb7314ae58dcc6aee9a20bf224c386ff5e80f7e4cf2`
        - 加载 `extracted_contracts/2024-01/MIMSpell2_exp/addresses.json` 生成 `AddressInfo` 列表；可选读取 `mapping_seeds.json`，并从环境变量补充攻击者/执行器地址。
        - 调用 `StateCollector.collect_state()` 收集攻击前状态并写入 `attack_state.json`。
        - 因为 `collect_after=True` 且攻击交易存在，继续查询攻击交易所在区块号并再次调用 `collect_state()`，写入 `attack_state_after.json`。
    - **输入 (Input)**：
        - month: `str` ("2024-01")
        - event_name: `str` ("MIMSpell2_exp")
        - event_dir: `Path` (`extracted_contracts/2024-01/MIMSpell2_exp`)
        - collect_after: `bool` (`True`，默认行为)
    - **输出 (Output)**：
        - `extracted_contracts/2024-01/MIMSpell2_exp/attack_state.json`
        - `extracted_contracts/2024-01/MIMSpell2_exp/attack_state_after.json`（若攻击交易哈希可用）
        - 返回 `bool` 表示事件处理成功/失败
    - **关联的辅助步骤**：
        - **ForkExtractor.extract_fork_info**：解析 fork 链与区块号 (In: exp 文件内容, Out: ForkInfo)
        - **ForkExtractor.extract_attack_tx_hash**：解析攻击交易哈希 (In: exp 文件内容, Out: tx hash)
        - **AttackStateCollector._get_attack_block_number**：通过交易回执获取区块号 (In: tx hash, Out: block number)
        - **json.load/open**：读取地址与映射配置 (In: addresses.json/mapping_seeds.json, Out: AddressInfo 列表/映射配置)

3. #### 步骤 3：区块状态采集（StateCollector.collect_state）
    - **类型**：核心步骤
    - **功能详解**：
        - 通过 `RPCManager.get_web3(chain)` 获取 Web3 连接，读取目标区块头用于校验与元数据填充。
        - 组装地址候选集（PoC 中的地址 + 环境变量注入的额外地址），用于后续 ERC20 余额查询。
        - 若启用并发且地址数量 > 3，则使用线程池并发执行 `_collect_address_state()`；否则串行处理。每个地址收集：
            - 基础链上信息：余额、nonce、合约字节码
            - 若为合约：调用 `_collect_storage()` 抓取 storage
            - 若为合约：调用 `_collect_erc20_balances()` 采集余额并推断 balance slot
        - 从已收集的 storage 中识别潜在地址并批量验证合约代码，若发现新合约地址会再次拉取其状态。
        - 生成 `metadata`（链、区块、时间、收集方式等）与 `addresses` 全量状态，并在存在 `mapping_seeds` 时补充映射槽位。
    - **输入 (Input)**：
        - chain: `str` ("mainnet")
        - block_number: `int` (19118659 或攻击交易所在区块)
        - addresses: `List[AddressInfo]`
        - attack_tx_hash: `str | None` (本次为攻击交易哈希)
        - mapping_seeds: `Dict | None`
        - protocol_hint: `str` ("MIMSpell2_exp")
    - **输出 (Output)**：
        - `Dict[str, Any]`：包含 `metadata` 与每个地址的 `balance/nonce/code/storage/erc20_balances`
        - 可能更新 `trace_cache`（缓存 trace 结果以复用）
    - **关联的辅助步骤**：
        - **RPCManager.get_web3**：创建并缓存 Web3 实例 (In: chain, Out: Web3)
        - **StateCollector._collect_addresses_concurrent**：线程池并发采集地址状态 (In: addresses, Out: Dict[address, state])
        - **StateCollector._collect_address_state**：采集单地址基础信息与合约扩展信息 (In: address, Out: StateSnapshot)
        - **StateCollector._discover_addresses_from_storage**：从 storage 中发现新合约地址 (In: address_states, Out: List[address])
        - **StateCollector._apply_mapping_seeds**：按配置补全映射槽位 (In: mapping_seeds, Out: storage 补充)

4. #### 步骤 4：合约 storage 收集主逻辑（StateCollector._collect_storage）
    - **类型**：核心步骤
    - **功能详解**：
        - **Phase 1：Trace 驱动**
            - 当 `attack_tx_hash` 可用且 `use_trace=True` 时，调用 `_collect_storage_from_trace()` 使用 `debug_traceTransaction` + `prestateTracer` 获取攻击交易访问过的所有 storage slots。
            - 将 slot 列表转为整数后批量读取链上实际值；若批量 RPC 失败率高则降级并发或串行读取。
            - Trace 结果会缓存到 `trace_cache`，避免同一交易重复 trace。
        - **Phase 2：源码补全**
            - 若启用 `use_source_supplement`，通过 `_find_source_dir()` 定位 `extracted_contracts` 中的源码目录，再用 `_infer_contract_name()` 推断合约名。
            - 调用 `forge inspect <file:contract> storage-layout` 获取 layout；抽取基础 slot 集合后，以 `_merge_storage_with_layout()` 只补充 layout 中缺失且非零的 slots。
        - 发生 RPC trace 不支持时会抛出异常终止（提示更换支持 debug 的节点）；若是限流/服务器错误则等待 10 秒重试一次。
    - **输入 (Input)**：
        - address: `str` (被采集的合约地址)
        - block_number: `int`
        - attack_tx_hash: `str | None`
        - protocol_hint: `str` ("MIMSpell2_exp")
    - **输出 (Output)**：
        - `Dict[str, str]`：storage slot 到 hex 值的映射
        - 可能更新 `trace_cache` 与 `unsupported_trace_chains`
    - **关联的辅助步骤**：
        - **StateCollector._collect_storage_from_trace**：trace 解析并返回访问过的 slots (In: tx hash, Out: storage dict)
        - **StateCollector._batch_read_storage**：批量/并发读取 slots (In: slots, Out: storage dict)
        - **StateCollector._find_source_dir**：定位源码目录 (In: address/protocol_hint, Out: Path)
        - **StateCollector._infer_contract_name**：推断合约名 (In: source_dir, Out: contract name)
        - **StateCollector._get_storage_layout**：调用 `forge inspect` 获取布局 (In: contract_identifier, Out: layout)
        - **StateCollector._merge_storage_with_layout**：补全缺失 slots (In: trace + layout, Out: merged storage)
