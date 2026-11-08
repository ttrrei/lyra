# Lyra 从总体设计到 0005 的整体对抗性检验

> **English:** [overall-design-through-0005.en.md](./overall-design-through-0005.en.md)

## 结论

Lyra 的组件分层总体清晰：数据进入、特征构建、YAML 编译、past-only SQL 和逐标的交易状态机都有对应实现。但 0004 信号查询与 0005 bar 输入之间的装配契约尚不完整。当前代码和测试**不能证明产品已可进入可靠的策略搜索**：数据完整性、坏输入处理、partial bar 语义和融资日计数仍有跨阶段缺口。0006 runner 尚未实现，R12 的 AI 方向/分支/context 工作流、0007 OCI push/backup、0008 332 策略迁移和 0009 doctor/收尾也仍在后续阶段；这是尚未完成，不是把阶段顺序当作实现缺陷。

本报告只记录发现与建议，没有修改运行时代码。

## 范围与验证

对照 `docs/requirements.md` R1–R12、`docs/hld.md`、0001–0005 决策文档、`docs/ACTION_LOG.md` 当前状态及 0002–0005 实现，沿 OCI → 清洗/聚合 → feature builder → compiler → trade engine 检查数据、时间、成本与产物边界。

- `.venv/bin/python -m pytest -q`：**187 passed**。
- `.venv/bin/python -m pyflakes lyra tests`：通过，无输出。
- 另做定向探针：同大小但内容不同且无远端 MD5 的对象判断、损坏 ZIP、空 instrument/time 键、feature 输出路径穿越、多笔交易共享 `trading_days`、真实 bid/ask 查找、legacy exit typo、numeric/Boolean 列比较及混合标的输入。
- 未在本轮重新执行真实 OCI 下载、21 标的真实数据 E2E 或 0006 runner E2E；以往日志中的成功记录不视为本轮复测。

## 发现

### P1 — 阻止可靠结果的缺陷

#### R1. OCI 缺少 MD5 时用文件大小当作内容一致证明

**证据：** `lyra/oci_client.py:202–213`。远端有 `md5` 时比较 MD5；无 MD5 但有 `size` 时只比较本地字节数。探针用同样大小的不同内容、远端无 MD5，函数仍返回“本地已是最新”，因而跳过下载。

**影响：** 同对象名的新内容可能继续被当作旧数据使用，破坏 R6/I20 的内容完整性与可复现性。文件大小不是内容校验。

**建议：** 当远端没有可验证的内容摘要时，不能仅凭大小命中缓存；应重新下载并计算本地 SHA256，或以其他可信远端校验元数据验证后才复用。

#### R2. 损坏归档被静默跳过，后续可能覆盖成空数据集

**证据：** `lyra/pull.py:75–90` 在 `testzip()` 发现坏成员时直接 `continue`。`lyra/pipeline.py:118–145` 先清除目标 CSV，再清洗；若没有有效输入，会写零行 bronze 和零行 5m/1h Parquet，流程没有因“预期数据未成功提取”失败。

**复现：** 构造 CRC 错误的 ZIP，提取器返回空列表而不报错。与 `clean_target=True`、空 bronze 分支组合时，可把损坏输入表现成成功的空结果，并覆盖之前的派生数据。

**影响：** 数据损坏和数据集意外为空无法与合法空输入区分；下游可能把空回测当成有效结果。

**建议：** 对预期必需的数据集采用 fail-closed：任何归档校验失败或有效提取数低于预期都应终止，且在新一代产物完整验证之前不要覆盖旧产物。

#### R3. `instrument` / `time` 必需列存在，不等于键值有效

**证据：** `lyra/clean.py:106–115` 只验证必需列名；`lyra/clean.py:205–232` 过滤 `is_complete`、按 `(instrument,time)` 去重，但没有 `instrument IS NOT NULL` / `time IS NOT NULL` 或空字符串检查。现有质量门只管价格、spread、volume。

**复现：** 空/NULL `instrument` 或 `time` 行能通过 clean 并成为 bronze 行。NULL 标的会进入 instrument 枚举，之后 feature 构建以 `instrument = NULL` 查询不到对应行；NULL 时间则可能产生无法排序/执行的特征行。

**影响：** 关键键的坏值未在数据入口拒绝，故障延后到 aggregate、feature builder 或策略运行阶段，且错误更难定位。

**建议：** 在写 bronze 前强制键非 NULL、非空且格式合法；同时明确并测试时间必须是 UTC、可排序的有效观测时间。

#### R4. `trading_days` 是每次 `simulate()` 一个标量，不能表达每笔交易的持仓日数

**证据：** `lyra/trade_engine.py:106–111` 把 `trading_days` 定义成可选标量；`_finish()` 在每笔交易结束时都把同一个值传给 `_day_count()`（约 157–172 行）。一次 `simulate()` 可以返回多笔持仓区间不同的交易。

**复现：** 同一次调用里两笔持仓分别跨 2 小时和 5 小时，传 `trading_days=5` 后两笔都按 5 天融资计费。单一标量无法由 0006 正确表示每笔不同的周末/节假日跨越。

**附带默认风险：** `trading_days=None` 仍按自然日计算，尽管 R4/O15 定义的是排除周末与市场假日的交易日。忘记传入值的调用方会静默得到与已定需求不同的成本。

**建议：** 在 0006 接入前把接口改成按实际 entry/exit 区间计算日数（例如由确定性的交易日历计算器逐笔计算），并让 Lyra 合约路径在缺少交易日计数时 fail-closed。Nova 对照可作为显式兼容测试模式，不能成为默认业务语义。

#### R5. partial bar 的设计契约冲突，feature builder 会消费它们

**证据：** HLD §2.1 `docs/hld.md:57` 写“partial 桶丢弃并计数”；0002 I21（`docs/decisions/0002-ohlcv-data-sync.md:296`）规定保留窗口内已有 bar、用 `n_bars` 标记部分 bar；`lyra/aggregate.py:92–106` 按现有行聚合并输出 `n_bars`，测试明确断言 partial 5m/1h 桶存在；feature 表会原样带出 `n_bars`，计算时不按完整度过滤。

**影响：** 1m 数据的边界/缺口可能形成 OHLC 观察点数不足的 5m/1h 行，而指标和策略把它作为普通 bar 使用。如果真实契约是“丢弃”，当前代码结果错误；如果 0002 的“保留”是最新决定，HLD 误导后续开发和 AI。

**建议：** 以 0002 I21 当前更具体的实现决策为准时，应修正 HLD 并在 0003/0004 消费契约里明确 `n_bars` 的含义；若产品想丢弃 partial bar，则需同步改 0002 决策、聚合及测试。不能让消费者自行猜测。

#### R6. 编译器信号查询没有 OHLC，不能直接满足交易引擎输入契约

**证据：** `lyra/compiler.py:283–303` 的 SELECT 只输出 `instrument`、`time` 和四个 entry/exit 信号；`lyra/trade_engine.py:114–118` 要求每行还包含 `mid_o/mid_h/mid_l/mid_c`。本轮用示例 YAML 编译后检查 SQL，确认 OHLC 不在结果列中。

**影响：** 将编译 SQL 的结果直接传给 `simulate()` 会因缺少 `mid_o` 等字段失败。HLD 说 0006 执行 SQL 后驱动状态机，但尚未定义或实现按 `(instrument,time)` 把信号与价格 bar 对齐的 adapter。

**建议：** 在 0006 决策中明确唯一装配路径：信号查询必须保留时间键，并与同一 timeframe 的 OHLC 逐键对齐；对缺行、重复键、NULL 键 fail-closed。添加从 YAML → SQL → 对齐 bar → `simulate()` 的端到端测试。

#### R7. `_quote()` 查找的 bid/ask 列名与数据契约不一致

**证据：** `lyra/trade_engine.py:83–103` 把 `point="mid_o"` 拼成 `bid_mid_o` / `ask_mid_o`；clean 输入契约列名是 `bid_o` / `ask_o`，聚合层当前则只输出 mid OHLC。探针传入 `mid_o=100, bid_o=99, ask_o=101` 后 long/short quote 都返回 100，实际 bid/ask 被忽略。

**影响：** 若 runner 传入了真实 quote 列，引擎仍会退回 mid 和配置 spread 计算成交价，忽略实际点差；因此执行价格和成本可能失真。当前 0002 聚合层只保留 mid 数据，需先明确 runner 是否会使用真实 quote。

**建议：** 统一 trade engine 的 quote 字段名与输入 schema（例如映射 `mid_o`→`bid_o/ask_o`），并对实际 quote 优先级、缺失 fallback 和价差 double-count 增加测试。

#### R8. 旧式 `exit.feature` 块内拼写错误会静默丢弃退出条件

**证据：** `lyra/strategy_schema.py:703–727` 将顶层 `feature` 作为兼容键；只有内层含 `when` 才会解析，内层其它键没有 allow-list 校验。探针传 `exit: {feature: {whne: ...}}`，schema 接受策略且 `exit_long`、`exit_short` 都为 `None`，compiler 输出 `FALSE` 退出条件。

**影响：** 用户以为启用了指标退出，实际只剩 stop / time / end-of-data 退出；策略仍能 validate/compile，结果语义悄然改变。

**建议：** legacy `feature` 映射必须要求唯一 `when` 键并拒绝未知内层键；或弃用该旧式形状。补拼写错误拒绝测试。

### P2 — 已知的跨阶段风险，尚未关闭

#### R9. feature-vs-feature 比较没有校验左右列的值域类型

**证据：** `lyra/strategy_schema.py:387–403,427–464` 解析右侧已知列时取到但丢弃其 `FeatureKind`；AST 仅保留左列 kind。`lyra/compiler.py:213–219` 将两个列直接比较。比如 numeric feature 与 Boolean state 列的比较可通过 validate/compile；DuckDB 执行时会抛 `BinderException`（本轮 `DOUBLE > BOOLEAN` 探针复现）。

**影响：** 合法 YAML 并不保证可执行；错误延迟到 run 才出现。不同单位但同为 numeric 的比较也可能在语法上通过并产生无意义信号。

**建议：** 编译前验证左右列 kind/单位兼容；不兼容时在 YAML 路径上 fail-fast。对 boolean/state、event、ordinal、continuous 的成对组合补矩阵测试。

#### R10. instrument 可构造越出数据根目录的 feature 输出路径（0003 批次1挂起项）

**证据：** `lyra/features.py:776–786` 直接将 instrument 拼入文件名；`run_features()` 在 855–860 行将该路径写到最终位置，没有验证文件名或解析后的路径边界。探针传入 `../../../../tmp/...` 后，输出路径落在 data root 之外。

**影响：** 一旦输入数据或 alpha 数据带有异常 instrument 值，feature 写入可能覆盖仓库/用户目录中的同名路径。0003 批次1将此项挂到 0004/0007；本次确认仍未关闭。

**建议：** 在 clean 输入边界验证 instrument slug，并在最终写入前验证 resolve 后路径仍位于配置的数据根目录内。不要只依赖 OCI 数据“通常受控”。

#### R11. 多标的 feature 写入非原子，失败后目录可混用新旧版本（0003 批次1挂起项）

**证据：** `lyra/features.py:758–773` 直接覆盖最终 Parquet；`run_features()` 逐标的写出（855–862），没有 staging 目录、manifest 或一次性发布步骤。

**影响：** 第 N 个标的计算失败后，前 N−1 个已经是新版本，余下仍是旧版本；Catalog/后续运行可能读取混合生成。既有 0003 review 已将其挂到 0004/0007，但当前仍存在。

**建议：** 将整次生成写入独立 staging，完整性/版本/标的集校验通过后再原子切换可见指针；失败时保留上一代完整产物。

#### R12. alpha 特征代码语义未绑定到 feature 版本标识（0003 批次1挂起项）

**证据：** `lyra/features.py:584–599` 的 `feature_version_string()` 哈希注册名、参数和 warmup，并纳入 Python/NumPy 版本；不包含 alpha 模块源码哈希或 alpha 版本标签。现有决议将 provenance 完整边界挂到 0007。

**影响：** alpha 实现可变而版本标识不变，使同一标识下的 feature 值可能改变，削弱可复现性与 OCI immutable-object 的审计链。

**建议：** 0007 定稿前，至少要规定 alpha feature source/contract hash 如何进入 Parquet/run provenance，并验证变更会改变身份。

#### R13. clean 去重的“原行序”平局规则没有落到 SQL

**证据：** 0002 要求重复键按“payload 非空数 → 源文件名 → 原行序”确定存活行（`docs/decisions/0002-ohlcv-data-sync.md:85,145`）。实际 `lyra/clean.py:221–226` 仅按 `_payload_score DESC, _source_file ASC, time ASC` 排序；同一文件、同键、同 payload score 的不同内容没有唯一排序字段。

**影响：** I18 的确定性存活行规则不完整；DuckDB 不承诺对 ORDER BY 完全相等的候选稳定取同一条。当前两次运行测试不覆盖该冲突输入。

**建议：** 在读 CSV 时保留稳定行号并纳入排序；加同文件、同分、不同 payload 的重复行测试。

#### R14. `simulate()` 接受混合标的序列但没有 fail-fast

**证据：** `simulate()` 文档要求 one instrument（`lyra/trade_engine.py:112–118`），实现没有验证输入唯一标的。探针在 A 标的发出 entry、随后把 B 标的 bar 放入同一序列；引擎无报错并把交易记在 B 名下。

**影响：** runner 若误把多标的行传入一个状态机，入场信号、成交价和报告标的可能错配。即使 runner 设计为逐标的调用，API 也没有防止错误调用。

**建议：** `simulate()` 开始时验证所有 bars 只有一个 instrument，并验证时间严格有序；不满足时抛出明确异常。

### P3 — 文档和交付一致性

#### R15. OCI 一键命令名称冲突

**证据：** requirements R7 写 `lyra sync`；HLD §2/§8 和 0001 写 `lyra backup`。0007 尚未实现，因此尚无代码可消除此歧义。

**建议：** 0007 决策前统一唯一的用户命令名，并确定是否保留兼容别名。

#### R16. 0001 / 0002 决策元信息仍标成 Proposed

HLD 与 ACTION_LOG 已记录 0001、0002 完成，决策文档元信息仍分别写“提案/待用户审批”。这是审计状态不一致，不是当前运行时缺陷；应在最近一次文档维护中同步真实状态，保持历史决策只增不删。

#### R17. 锁文件在 HLD/doctor 预期中，但仓库没有对应文件

HLD 描述 `requirements.lock` 并要求它固定传递依赖，`pyproject.toml` 也有相应注释，但仓库当前没有 `requirements.lock`、`uv.lock` 等锁文件。R8 的“相同版本可复现”和 doctor 的依赖检查目前缺少文档所说的锁定输入。

**建议：** 在 0009 决定并落地唯一锁定机制，或修正文档，避免把不存在的文件当作已交付。

## 已验证的设计面与阶段门槛

- 0004 compiler 生成受控、参数化的 past-only SQL；temporal 运算要求完整 N 行且保留 NULL 语义，未发现新的 look-ahead 缺口。0004 批次2发现的修复在本轮全套测试中继续通过。
- 0005 已有 next-observed-open、2% adverse stop、gap 按实际开盘成交、同 bar stop 优先和单标的一笔状态机测试；这些语义没有被本轮发现推翻。
- 但当前没有 `lyra run`、月度 metrics/report、逐交易日历集成、R12 多 AI tracks/context/分支生命周期。0005 Python API 并不构成端到端策略搜索入口；O16 仍阻塞 0008 的 332 策略迁移。
- 因此建议先处理 R1–R8（数据完整性、执行语义和 0004→0005 接口），再实现 0006；R10–R12 应在 0004/0007 消费与发布边界关闭，R15–R17 在后续决策/doctor 阶段收口。

## 历史发现承接

R10、R11、R12 分别对应 0003 批次1 review 的 H1、H4、H3，已被当时挂起到 0004/0007；本报告不把它们伪装成新发现，而是确认当前代码仍未处置。0005 融资交易日问题在批次3增加了 `trading_days` 支持和 fail-closed 时间校验，但本报告发现该标量仍不能表示一次调用中的多笔交易区间。
