### 1. 执行概览
*简要说明程序通过该命令启动后，主要执行了什么任务。*

该命令启动脚本后从 `__main__` 进入 `main()`，解析 `--protocol MIMSpell2_exp` 并构建提取器，仅筛选匹配该协议名的 PoC 脚本，依次执行静态/动态地址提取、地址合并与链上补全、源码或字节码下载，最后落盘结果并生成摘要统计。

### 2. 执行流程详细拆解

*(按时间顺序排列，使用有序列表)*

#### 步骤 1：ContractExtractor.extract_all（调度与目标脚本筛选）
- **类型**：核心步骤
- **功能详解**：作为全流程调度入口，先扫描测试目录中符合 `YYYY-MM` 结构的子目录，再筛选脚本名等于 `MIMSpell2_exp` 的 `.sol` 文件生成 `ExploitScript` 列表；设置统计基线后逐个调用 `_process_script` 处理脚本，成功/失败计数分别累加；全部处理完后写入未验证合约列表与摘要统计并输出汇总日志。
- **输入 (Input)**：
    - date_filters: None（未传 `--filter`）
    - protocol_filter: `"MIMSpell2_exp"`
    - limit: None
    - test_dir/output_dir: 使用脚本内配置的默认值
- **输出 (Output)**：
    - 目标脚本列表（仅包含协议名匹配项）
    - 统计计数更新（total/success/failed/addresses 等）
    - 未验证合约列表与摘要统计落盘
- **关联的辅助步骤**：
    - **`main` / `argparse`**：解析命令行参数 (In: argv, Out: args)
    - **日志配置**：设置日志级别/文件处理器 (In: args.debug/args.log_file, Out: 记录器状态)
    - **`ContractExtractor.__init__`**：初始化静态/动态分析器、源码下载器、可选链上数据抓取器并准备输出目录 (In: 目录与 API key 配置, Out: 组件实例与目录就绪)

#### 步骤 2：StaticAnalyzer.analyze_script（静态地址与链信息提取）
- **类型**：核心步骤
- **功能详解**：读取目标脚本源码后，先从注释中提取关键字相关的地址（支持注释 URL 或直接地址），再从代码中解析常见地址定义模式（常量、类型转换、接口调用等）；对候选名称进行黑名单过滤和“类型名优先”选择，并生成别名列表；随后解析 `createSelectFork` 或注释 URL 推断链类型，并提取脚本中指定的 fork 区块号；去重后返回静态地址集合。
- **输入 (Input)**：
    - script: ExploitScript（含文件路径与协议名）
    - content: 脚本源码文本
- **输出 (Output)**：
    - static_addresses: List[ContractAddress]
    - chain: Optional[str]（同时回填 `script.chain`）
    - block_number: Optional[int]（回填 `script.block_number`）
- **关联的辅助步骤**：
    - **`_extract_from_comments`**：按关键字扫描注释并提取地址 (In: 源码文本, Out: 地址列表)
    - **`_extract_from_code`**：用正则匹配地址定义并选择名称/别名 (In: 源码文本, Out: 地址列表)
    - **`_select_best_name` / `_build_aliases`**：挑选更有意义的名称与别名 (In: 候选名/上下文, Out: name/aliases)
    - **`_extract_chain` / `_infer_chain_from_comments`**：推断链类型 (In: 源码文本, Out: chain)
    - **`_extract_block_number`**：提取 fork 区块号 (In: 源码文本, Out: block_number)

#### 步骤 3：DynamicAnalyzer.analyze_script（forge trace 动态地址提取）
- **类型**：核心步骤
- **功能详解**：通过 `forge test --match-path <脚本相对路径> -vvvv` 运行 PoC，输出重定向到临时文件避免管道阻塞；解析 trace 中 CALL/CREATE 记录以及 Traces 段落的全部地址，并过滤零地址/预编译/混合数据等无效地址；如未捕获到地址则追加 `-vvvvv` 重跑以强制输出更完整调用栈，最终返回动态地址集合。
- **输入 (Input)**：
    - script: ExploitScript（含文件路径）
    - skip_tests: 默认跳过列表（用于稳定性）
- **输出 (Output)**：
    - dynamic_addresses: List[ContractAddress]
    - 可能的警告日志（缺少 Traces 或测试失败）
- **关联的辅助步骤**：
    - **`_run_forge_test`**：执行 `forge test` 并收集输出 (In: 脚本路径/flags, Out: stdout+stderr 文本或 None)
    - **`_parse_trace` / `_extract_traces_body`**：正则解析调用栈地址 (In: forge 输出, Out: 地址列表)
    - **`is_valid_address`**：过滤明显无效地址 (In: 地址字符串, Out: bool)

#### 步骤 4：地址合并与别名补全（_merge_addresses + apply_labels）
- **类型**：核心步骤
- **功能详解**：将静态与动态地址按小写地址合并，优先保留更完整的 `name/chain/aliases`，并将脚本推断出的链类型强制回填到所有地址；随后扫描脚本中的 `vm.label`，解析地址表达式（去掉 `address()/payable()` 包装并回溯变量赋值）并把 label 写入别名集合；同时创建脚本专属输出目录并更新地址统计。
- **输入 (Input)**：
    - static_addresses: List[ContractAddress]
    - dynamic_addresses: List[ContractAddress]
    - chain: Optional[str]
    - content: 脚本源码文本
- **输出 (Output)**：
    - merged_addresses: List[ContractAddress]（链类型与别名已补全）
    - summary.total_addresses 累加
    - 脚本输出目录就绪
- **关联的辅助步骤**：
    - **`_merge_addresses`**：地址去重与字段合并 (In: 静态/动态地址, Out: 合并后的地址列表)
    - **`apply_labels`**：解析 `vm.label` 并追加别名 (In: 源码文本/地址列表, Out: label 应用数量)
    - **`_resolve_label_expr` / `_resolve_address_from_var`**：解析 label 对应的真实地址 (In: 表达式/源码, Out: 地址或 None)
    - **`_load_existing_addresses` / `_calculate_diff`**：diff 模式下读取基线并比较 (In: 输出目录/地址列表, Out: diff 结果；当前命令未启用)

#### 步骤 5：链上信息补全（_enrich_with_onchain_data，条件执行）
- **类型**：核心步骤
- **功能详解**：若链类型已识别且链上数据抓取器可用，则批量查询链上元数据，补全 `onchain_name/symbol/decimals/is_erc20/semantic_type` 等字段；同时根据符号与名称生成多个别名变体并去重，以提升后续识别与归类能力；若抓取器不可用或查询失败则直接跳过。
- **输入 (Input)**：
    - addresses: List[ContractAddress]
    - chain: 识别出的链类型
- **输出 (Output)**：
    - enriched_addresses: List[ContractAddress]（字段与别名可能被更新）
- **关联的辅助步骤**：
    - **OnChainDataFetcher 初始化**：从配置读取 API key (In: 配置文件路径, Out: fetcher 实例或 None)
    - **`batch_fetch_contracts`**：异步批量查询 (In: 地址列表/链类型, Out: 地址->元数据映射)
    - **别名构建逻辑**：增加符号大小写与 `I` 前缀变体 (In: symbol/name, Out: aliases)

#### 步骤 6：源码/字节码下载与代理解析（_download_sources_with_impl_collection）
- **类型**：核心步骤
- **功能详解**：先通过 RPC 批量预检查地址是否为真实合约，过滤无效地址后并发下载源码；对已验证合约保存源码、ABI 与元数据，对未验证合约回退下载字节码并记录元数据；随后基于 EIP-1967/EIP-1822/Beacon 等存储槽进行代理检测，发现代理则递归下载实现合约并记录代理信息；若已获取源码与 runtime code，则调用本地 solc 解析 immutable 变量并落盘；最后补充创建交易哈希与构造交易 input，扫描元数据收集实现合约地址并更新地址清单。
- **输入 (Input)**：
    - addresses: List[ContractAddress]
    - chain: 识别出的链类型
    - output_dir: 脚本输出目录
    - unverified_contracts: 共享未验证列表
- **输出 (Output)**：
    - 合约源码/字节码/ABI/元数据等落盘
    - 代理实现合约地址集合（用于回填地址清单）
    - 统计信息更新（verified/unverified/bytecode-only）
- **关联的辅助步骤**：
    - **`batch_check_contracts_exist`**：RPC 并发检查合约存在性 (In: 地址列表, Out: 有效地址集合)
    - **`APIKeyPool.acquire_key`**：API key 限流与并发管理 (In: timeout, Out: api_key)
    - **`download_contract`**：下载源码或字节码并处理代理递归 (In: address/chain/output_dir, Out: success/bytecode_only)
    - **`_fetch_source_code` / `_save_contract_files`**：区块浏览器 API 拉取并保存源码 (In: address/api_url, Out: 源码文件与元数据)
    - **`ProxyDetector.detect_proxy`**：读取存储槽判断代理类型 (In: address/chain, Out: proxy_info 或 None)
    - **`ImmutableExtractor.try_extract_and_save`**：解析并保存 immutable 变量 (In: runtime/源码/输出目录, Out: immutables 文件)
    - **`_enrich_constructor_data`**：补充创建交易与构造参数 (In: address/chain, Out: 元数据更新)
    - **`_save_addresses`**：回填实现合约后更新地址清单 (In: 地址列表, Out: 地址清单落盘)
