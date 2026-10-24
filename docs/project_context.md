# 脚本调测轨迹经验提取项目上下文

更新时间：2026-10-24  
GitHub 维护分支：`develop`；GitHub 服务发布分支：`main`；skill 开发包随 `develop` 每次更新自动发布。内网实际部署仓库为 CodeHub `CoreTool/CoreAI/Data/AgentMemory.git`，主分支为 `master`，与 GitHub 分支区分记录。

## 1. 背景与目标

在 memory 服务中定时读取 CloudSpider 的脚本调测 Step 数据，将相同 `caseId + testUser` 的全部历史 Step 整理成完整轨迹，从有效修复中提取经验并写入云见经验中心。

整体流程：

```text
读取更新数据
→ 查询完整轨迹
→ 找出有效修复点
→ 大模型提取经验
→ 新建、覆盖或删除经验
→ 保存任务进度和轨迹处理结果
```

经验正文保存在 Elasticsearch，SQL 只保存增量读取位置、轨迹处理状态和经验引用。

## 2. 已确认的业务规则

### 2.1 轨迹和经验粒度

- 使用 `caseId + 原始 testUser` 查询和标识一条完整轨迹。
- 同一轨迹中出现不同 `groupId` 时，按产品分开处理。
- 一条轨迹可能包含多个有效修复点，每个有效修复点提取一个直接关联的主失败现象，并生成一条经验。
- 不同轨迹即使失败现象相似，也分别保存，不进行跨轨迹合并。
- 失败现象格式为“主语 + 核心失败表现”，由大模型根据接口可见的日志和上下文总结，不包含根因和修复动作。

### 2.2 有效经验判断

修复有效只看接口 `fixResult`：

- `success`、旧值 `PASS`：修复有效；
- `fail`、旧值 `FAIL`：修复无效；
- 其他值：结果未知。

生成经验还必须满足：

- `diffContent.hasChanged=true`；
- `changedLines` 非空；
- 修改与主失败现象直接相关；
- 接口当前可见数据足以支持结论。

无成功修复、没有实际修改、只增加日志或快速失败、修改与故障无关、证据不足的记录不生成经验。完整轨迹仍从接口分页读取，模型输入保留有效且实际修改的修复点，并为每个修复点保留之前最多 3 个 Step 作为上下文（上下文 Step 可以没有修改）；该数量可配置。`errorCause` 只有链接，从模型输入中排除，不下载完整日志。

### 2.3 经验内容

经验使用五段式 Markdown：

- `Debug Trace`：上次失败、本次修改、修改后结果，并保存来源用例 `caseId`、真实 `testUser` 和来源 Step；用例编号以正文中的“来源用例：”行保存，未单独写入 ES metadata，详见 7.5；
- `Error Log`：失败分类行和核心错误；
- `Diff`：直接写入修复 Step 的原始 `diffContent.changedLines`，以 diff 代码块显示，不由模型改写；
- `Root Cause`：根据日志和修改说明根因，区分事实和推断；
- `Pattern`：总结触发条件和经过验证的修复动作。

### 2.4 用户和产品

- 云见场景固定为“测试脚本调测经验”，`scene_id=421`。
- `product_id` 使用字符串形式的 `groupId`；接口 `groupName` 保存到 `product_name`。
- 上游 `product` 字段尚未提供，当前不填写 `metadata.product`，接口补充后再写入。
- `testUser` 为 `"no user"`、空字符串或 `null` 时，写入 `user_id="0"`。
- 覆盖经验时，原 `user_id` 非 `"0"` 则保持不变；原值为 `"0"` 且新数据有真实用户时允许更新。
- Debug Trace 始终记录接口返回的真实 `testUser` 原值。

## 3. 上游接口

已提供两个 POST 接口：

### 3.1 增量查询

`/openapi/v1/scriptGenAgentTrajectory/listByUpdateTimeAndId`

请求字段：

- `updateTime`
- `id`
- `pageNum`
- `pageSize`

使用 `updateTime + id` 记录读取位置。增量结果只用于发现哪些 `caseId + testUser` 发生变化。

### 3.2 完整轨迹查询

`/openapi/v1/scriptGenAgentTrajectory/listByCaseIdAndTestUser`

请求字段：

- `caseId`
- `testUser`
- `pageNum`
- `pageSize`

发现轨迹变化后，重新分页读取该组合的全部历史 Step；模型输入再按产品和有效修复点筛选。历史查询逐页读取至 `hasNextPage=false`，每页 10 条；超过模型上下文预算时按修复过程拆批。

响应中的 `diffContent` 和 `customStruct` 是 JSON 字符串，需要再次解析。时间按北京时间处理；`startTime`、`endTime` 是毫秒时间戳。

## 4. 当前实现

核心实现已提交到 `develop`，主要文件包括：

| 文件 | 作用 |
| --- | --- |
| `memory_service/trace_experience_pipeline.py` | 查询 Step、筛选输入、调用模型、同步经验和失败续跑 |
| `db_operate/trace_experience_store.py`、`db_operate/sql_models.py` | 保存任务游标、轨迹状态及经验引用 |
| `project_configs/prompt_configs.py`、`project_configs/settings.py`、`constants.py` | Prompt、正式任务配置和专用常量 |
| `models/llm_caller.py` | 模型请求、超时和安全诊断 |
| `api/experience_api.py`、`memory_service/experience_manage.py` | 共用创建、覆盖、删除及产品过滤能力 |
| `task_runner.py` | 仅在 `env=prod` 且任务启用时注册调测经验任务 |
| `test/experience/test_trace_experience_pipeline.py`、`test/experience/test_trace_experience_api_compat.py` | 离线行为和原 API 兼容测试 |
| `docs/调测轨迹经验提取设计文档.md` | 详细设计 |

正式配置位于 `TASK_RUNNER_CONFIG['TRACE_EXPERIENCE_EXTRACT']`。本轮核查的 GitHub `develop` 仍为旧任务名 `trace_experience_prod_20260501`、起点 `2026-05-01 00:00:00`；2026-10-20 用户已在内网 CodeHub 仓库修改为新任务名和 9 月 13 日起点并反馈已部署，详见 7.2。本次 GitHub 更新仅同步上下文，不代表 GitHub 配置代码已同步。

调测经验任务仅在 `env=prod` 且 `enabled=True` 时注册。运行 `task_runner.py` 的进程启动后立即执行首轮；有积压时每轮结束后最多等待 60 秒继续，无积压时等待 24 小时再执行，整轮异常时按正常周期等待重试。它不是固定夜间任务，代码中固定时刻执行的是另一项 code-agent 流水线。本服务按单实例运行；仅更新 API 服务不等于调度进程已启动。

每页增量 10 条、每轮最多 100 页；每轮先重试最多 10 条待处理或失败轨迹。模型上下文预算 50000 token，最多输出 10240 token，模型输入排除 `errorCause`。正式配置按既定要求使用 `verify_tls=False`。任务的 SQL 表已使用 `--init-tables` 初始化。

脚本直接运行时默认初始化新增 SQL 表；手动执行一轮使用 `--once`，可再加 `--max-pages 1` 限制本轮增量页数。`--max-pages` 不限制本轮的待重试轨迹，也不限制每条轨迹的历史查询。

## 5. 经验新建、覆盖和删除

每个修复点使用固定经验 `doc_id`，依据为：

```text
数据来源 + groupId + fixStepId
```

因此：

- 固定 `doc_id` 不存在：新建经验；
- 固定 `doc_id` 已存在且内容变化：归档旧版本并覆盖；
- 固定 `doc_id` 已存在且内容相同：跳过；
- `fixResult` 明确变为 `fail/FAIL`，或模型合法返回 `valid=false、reason_code=unrelated`：删除本任务创建的对应经验；
- 模型请求失败或格式错误：保留已有经验，轨迹标记失败后等待重试。
- 模型合法返回证据不足（`reason_code=insufficient_evidence`）：保存 `action=keep` 及原因，保留已有经验但不新建；本身不触发失败重试，轨迹可标记 `done`。
- 修复结果未知：不作为有效修复点提取，也不因未知结果主动删除已有经验；本身不触发失败重试。

失败现象用于经验标题、正文和检索，不参与 `doc_id` 计算，也不用于覆盖其他轨迹的经验。

## 6. SQL 状态设计

### 6.1 `trace_experience_job_state`

记录增量扫描的位置，核心字段是 `last_update_time + last_id`。服务重启后从该位置继续读取。该游标不是所有经验已处理完成的日期，也不是已生成经验所关联 Step 的最大更新时间。每页先保存发现的轨迹及游标，再逐条处理该页关联的完整轨迹，处理结束后才读取下一页。

### 6.2 `trace_experience_record`

记录每条轨迹的处理状态，包括：

- 轨迹标识；
- 最近成功处理的完整轨迹摘要；
- `pending/done/failed` 状态；
- 重试次数和最近错误；
- 已生成经验的 `doc_id`、修复 Step、来源版本和写入完成状态；模型结果先保存，写入失败可复用结果重试。损坏的 `experience_refs` 只标记失败，不覆盖原值。

实际经验正文不保存在这两张表中。

## 7. 验证与已知现象

- 已用正式环境连接初始化 GaussDB 状态表，并验证上游分页、模型调用和 ES 写入。试运行曾处理 1000 条新发现轨迹：`completed=997`、`failed=3`、`created=28`、`updated=4`、`deleted=3`、`skipped=3`；这是试运行记录，不代表发布后的统计。
- 另一次单轮结果为 `discovered=3`、`completed=1`、`failed=2`、`has_more=True`；失败对应历史数据的 `JSONDecodeError`、`TypeError`，当时决定暂不清理上游旧数据（2026-10-20 的 ES 经验清理另见 7.2）。`has_more=True` 表示还有增量页待处理。
- 本地针对 `test_trace_experience_pipeline.py` 的离线测试已通过；测试使用模拟接口、模型、ES 和 SQLite，不代替生产环境连接验证。测试桩已覆盖模型重试窗口，验证部分批次失败时保留先前完成的修复。
- ES 按固定 `doc_id` 查询返回 404 表示此前不存在该经验，新建前出现属于正常现象；模型输出不完整时记录具体错误，已完成的结果可重试复用。
- 2026-09-17 一次 CodeCheck 任务因同项目版本级检查同时运行而未能创建（`CC.10010253.400`），后续报告缺失是连带结果；该日志没有给出源码检查结论。需在占用任务结束后复验流水线。


### 7.1 原始 Diff 异常与数据起点决定（2026-10-19～20）

- 样本为 `caseId=I_20_Test_Env`、原始 `testUser="no user"`、`groupId=1058`、修复 Step `1541157`，`updateTime=2026-09-12 13:07:13`。其已入库经验描述通过增加 `Gpd_AddService` 修复订阅服务不存在错误。
- 用户查询上游原始响应，确认 `diffContent.changedLines` 从编码声明、导入、类定义到整份脚本均为新增，与经验中的 Diff 一致；`hasChanged=true`、`fixResult=success`、顶层 `executeResult=PASS`。这确认全新增来自上游，尚不能仅凭全新增证明比较基线错误或确定真实修改动作；上游基线原因未在本轮给出最终结论。
- 完整轨迹接口首屏较早（该组合当时共 1783 条），改用增量接口定位：`listByUpdateTimeAndId` 请求 `{"updateTime":"2026-09-12 13:07:12","id":0,"pageNum":1,"pageSize":10}`，成功取得目标 Step。后续翻页沿用最后一条的 `updateTime + id`，保持 `pageNum=1`；完整轨迹查询的用户参数仍须使用原始 `"no user"`，不是入库用户 `"0"`。
- 因 9 月 12 日当天也存在上述样本，用户最终决定从北京时间 **2026-09-13 00:00:00** 起重新提取。这是本轮确定的数据范围，不代表已全面验证 9 月 13 日之后所有 Diff。
- 用户确认上游补齐的是此前为 null 的 **`groupName`**，且补名称没有改变旧记录的 `updateTime`。现有映射直接写入 `product.product_name`，不需新增字段处理。`groupId` 保存在 `product.product_id` 和 `metadata.group_id`；`product.pdu_name` 则在入库时按用户查询补齐，与 `groupName` 无关。
- 当前范围判定依据 Step 的 `updateTime`，不是执行 `startTime` 或经验入库时间。起点之前的 Step 不作为本次新增经验修复点，但仍可能作为前置上下文读取。

### 7.2 旧经验清理、重建配置与部署状态（2026-10-20）

用户本地目录为 `D:\agent-memory\AgentMemory`，使用项目虚拟环境和 PowerShell 操作；本轮是用户在内网执行，助手依据回传输出核验。

**已完成的备份与删除：**

- 正式 ES 索引：`prod_unified_experience_index_v4`；测试索引：`unified_experience_index_v4`。
- 线上 Mapping 已确认：`scene_id` 为 keyword；`metadata.source` 为 text，精确匹配使用 `metadata.source.keyword`。
- 删除范围为 `scene_id="421"` 且 `metadata.source.keyword="trace_experience"` 的全部当前经验，不加日期限制，不清空整个索引。
- 查询匹配 179 条。完整备份包含 `_index`、`_id`、`_source`（含向量），文件为 `D:\agent-memory\AgentMemory\backups\trace_experience_20261020_111113.jsonl`，回传 `BACKUP_OK / COUNT: 179`。
- 按备份 ID 删除前，逐条核验当前正文与备份一致；删除携带 `if_seq_no + if_primary_term` 防止并发修改后误删。刷新后回传 **`DELETED: 179 / ALREADY_MISSING: 0 / REMAINING: 0`**，确认当时该范围当前经验已清空。
- 本次直接删除 ES 文档，未调用业务删除接口，因此没有新增删除归档；既有历史归档不在本次清理范围。SQL 的 `trace_experience_job_state` 和 `trace_experience_record` 按方案保留。
- 本地首次查询默认加载测试索引且 ES 返回 401；当前 PowerShell 设置 `env=prod` 和用户提供的 `CRE_KEY` 后查询成功。仅记录环境变量名称，不记录密钥值。经验连接来自 `get_es_client() -> AI_test_es_client`；切换 env 会切换索引，不会自动切换该连接的固定凭据。
- 未收到单独停用旧任务的确认；删除后剩余 0 是当时结果，后续仍需确认旧实例已被替换，避免旧任务再次写入。

**重建配置与部署：**

内网远端为 `https://codehub-dg-y.huawei.com/CoreTool/CoreAI/Data/AgentMemory.git`，主分支 `master`。指导从最新 `origin/master` 新建 `personal/c00959281/trace-experience-rebuild-0913`，仅修改 `project_configs/settings.py` 两项：

```python
'job_name': 'trace_experience_prod_20260913_rebuild_20261020',
'range_start': '2026-09-13 00:00:00',
```

`enabled=True`、`range_end=None` 及提取逻辑保持不变。用户贴出的 diff 确认为这两项修改，`git diff --check` 无输出；随后用户反馈已部署，未提供内网 MR 编号或提交 SHA。

更换任务名会建立独立 SQL 游标和处理记录，避免沿用旧游标或已完成缓存；原任务名直接修改时间范围会报 `range_changed`。仅删除 ES 后重启旧任务不能保证重新生成。重建仍沿用固定 doc_id 规则，任务名不参与经验 ID 计算。

**截至 2026-10-20 的状态：179 条旧经验已备份并删除，用户已反馈新配置部署完成；当时尚未收到新任务首轮日志或新经验抽查结果。2026-10-21 用户已回报游标推进及可见经验，详见 7.4；仍不能认定重建全部完成。** 下一步检查 `listByUpdateTimeAndId` 请求、`trace experience summary=` 汇总及 `[TASK] 调测经验提取失败`，并核实调度进程、实际新任务名、补齐的产品名称及 Diff。

### 7.3 重跑后旧经验缺失排查（2026-10-21）

用户反馈此前能从“9 月 21 日的 Network_SCP_SbiHttps_08_05”得到一条经验，重跑后查不到。已在本地删除前的 JSONL 备份中按用例名称匹配，用户回传结果确认：

| 项目 | 备份中的值 |
| --- | --- |
| 用例 | `Network_SCP_SbiHttps_08_05` |
| 经验 ID | `tracefix_3d7be5895714ac0556ec0ff2cbcc978499ca58f9d39ddca0` |
| 标题／失败现象 | DISCNFPROFILE 配置添加因参数无效失败 |
| 原始调测用户 | `no user`（入库 `user_id="0"`） |
| 产品 ID／group_id | `1058` |
| 修复 Step | `1327580` |
| 关联 Step | `1282366`、`1327580` |
| 修复标记 | `success` |
| 修复 Step 更新时间 | **2026-09-06 16:04:17（北京时间）** |

旧经验记录的失败为 `ADD DISCNFPROFILE` 返回 `retcode 360041`、参数无效；Diff 为 chf1 和 chf2 的 `nfServices[0]` 增加 `scheme='https'`，另有合入类型注释变化。上述内容来自旧经验备份，本轮尚未取得当前上游原始 Step 进行复核。

**当前判断：备份中的修复时间早于本次重跑起点 2026-09-13。若上游 Step 1327580 的 updateTime 仍为 9 月 6 日，该修复点会被时间范围筛掉，不会重新生成经验；即使完整轨迹已读取到它也一样。** 本次是先删除全部旧经验、再按缩小后的范围重建，因此不能期待全部 179 条恢复。用户所说“9 月 21 日”的含义未确认，不能当成该修复点的更新时间，也不能断言是经验入库日期。

排查路径与判定：

1. 从 7.2 的本地备份按用例名称搜索，提取 `_id`、`metadata.fix_step_id`、`metadata.group_id` 和正文中的原始调测用户；已完成本样本定位。
2. 查询 `trace_experience_record` 中该 `case_id` 的所有任务记录，对比旧任务与 `trace_experience_prod_20260913_rebuild_20261020`；查看 `source_test_user_json`、`process_status`、`retry_count`、`last_error` 和 `experience_refs`。没有新任务记录只说明尚未发现该轨迹，需结合游标判断；`done` 不等于生成了经验。
3. 查询新任务的 `trace_experience_job_state.last_update_time + last_id`。SQL 时间按 UTC 保存，对照上游北京时间需加 8 小时；游标推进不代表此前所有轨迹均处理成功。
4. 调用完整轨迹接口 `listByCaseIdAndTestUser`，请求 `{"caseId":"Network_SCP_SbiHttps_08_05","testUser":"no user","pageNum":1,"pageSize":10}`，逐页到 `hasNextPage=false`，定位 `id=1327580`。核查当前 `updateTime`、`fixResult`、解析后的 `diffContent.hasChanged/changedLines`、`groupId` 及同产品前置上下文。不能用入库用户 `"0"` 代替原始 `"no user"`。
5. 按旧 `doc_id` 精确查询正式 ES，区分文档确实不存在和检索未召回；若 `groupId` 变化，固定经验 ID 也会变化。

本轮源码核查还确认：`experience_refs` 的 `action=put, done=true` 表示写入流程已完成；`keep` 表示模型判断证据不足，原因保存在 `reason`，不会新建经验；`delete` 可表示模型判断修改与故障无关。由 `fixResult=fail/FAIL` 触发的直接删除不新增对应删除引用，不能仅凭 refs 排除这一分支。证据不足本身不会自动将轨迹标成失败重试；旧经验清空后，`keep` 也没有旧文档可保留。

**待核实：尚未收到本样本的新任务 SQL 记录、当前上游 Step 或正式 ES 精确查询结果（任务级游标的后续反馈见 7.4），因此不能认定该轨迹已经跑过，也未完成生产现状的最终归因。** 本轮未恢复旧经验、未补跑、未修改提取代码或重跑时间范围。

### 7.4 游标日期、完成判定与后续增量运行（2026-10-21）

**用户反馈：** 按新任务名查询后，`cursor_time_beijing=2026-09-13 04:51:14`；同时已看到关联轨迹更新时间为 `2026-10-16 16:27:15` 的经验。尚未提供完整 SQL 行、该经验原始文档或最新一轮汇总，因此记录为用户观测，不据此认定全部重建完成或确定该经验的具体处理路径。

**源码确认的解释：**

- `Pipeline.run()` 通过增量接口按 `updateTime + id` 扫描，发现需要处理的 `caseId + testUser`；SQL 游标只记录这一步的位置。
- `Pipeline.process()` 随后调用 `StepClient.history()`，分页读取该组合的全部历史 Step。有效修复点按配置的 `range_start/range_end` 筛选，不以当前增量游标作为上限。
- 本次起点为 9 月 13 日，`range_end=None`。因此，扫描到某组合在 9 月 13 日的 Step 时，可以同时读取并提取该组合 10 月 16 日的有效修复；两种日期可以同时成立，不能以已有经验的最大日期判断整体进度。
- `TraceStateStore.discover()` 先保存该页发现的轨迹及游标，随后逐条处理完整轨迹，再扫描下一页。长轨迹、历史分页或模型耗时会使游标暂时不动；仅凭一次查询不能判定卡住。

**生产 GaussDB 查看方法（SQL 保存 UTC，展示北京时间加 8 小时）：**

```sql
SELECT
    job_name,
    last_update_time AS cursor_time_utc,
    last_update_time + INTERVAL '8 hours' AS cursor_time_beijing,
    last_id,
    updated_at + INTERVAL '8 hours' AS state_updated_beijing
FROM trace_experience_job_state
WHERE job_name = 'trace_experience_prod_20260913_rebuild_20261020';

SELECT process_status, COUNT(*) AS record_count
FROM trace_experience_record
WHERE job_name = 'trace_experience_prod_20260913_rebuild_20261020'
GROUP BY process_status;
```

- 隔几分钟比较 `cursor_time_beijing`、`last_id` 和 `state_updated_beijing`，结合运行日志判断是否持续推进。
- 查看对应任务最新一轮 `trace experience summary=`：`has_more=True` 表示仍有增量积压；当前无结束时间限制时，`has_more=False` 表示本轮已读到上游当时末尾。
- 再检查任务级 `pending/failed`：分别为待处理和失败待重试；`done` 只表示轨迹处理完成，不保证生成经验。
- 最新一轮 `has_more=False` 且无 `pending/failed`，才可表述为“截至该轮检查已追平并处理完成”；游标推进本身不代表此前轨迹全部成功。当前尚无这些完整结果，不能宣布跑完。

**后续自动增量：** 历史追平后无需切换配置，继续从保存的 `updateTime + id` 扫描新增或更新的 Step，发现变化后重新读取对应组合的完整历史并同步经验；服务重启也沿用原游标。有积压时每轮结束后最多等待 60 秒继续，无积压时等待 24 小时再检查，每轮按现有机制重试待处理或失败轨迹。保持当前 `job_name`、时间范围配置（`range_end=None`）和调度进程持续运行即可。未改变上游 `updateTime` 的字段补齐不会仅凭增量扫描自动被发现，仍适用 7.1 的说明。

本轮仅确认运行机制和查看方法，未修改代码、配置、游标，未执行补跑。

### 7.5 UPCF 经验导出及用例编号提取（2026-10-22，10-24 整理）

本轮由用户在内网项目目录 `D:\agent-memory\AgentMemory` 的虚拟环境和 PowerShell 中执行，助手依据用户回传输出核验；未修改线上经验、SQL 状态或提取逻辑。

**导出范围与结果：**

- 正式索引 `prod_unified_experience_index_v4`，精确匹配 `product.product_name="UPCF"`；不限制场景、来源、用户、版本、时间或质量状态，只导出当前文档，不含已删除文档及覆盖前的历史版本。
- 用户说明总量不超过 200 条，因此采用单次 `size=500、track_total_hits=True、_source=True` 查询，无需 Scroll。脚本核验查询未超时、无失败分片、命中总数精确且与取回数量一致。
- 初次结果为 `EXPORT_OK / UPCF_TOTAL: 33 / EXCLUDED: 0 / EXPORTED: 33`，保存完整 JSONL（`_index、_id、_source`，含返回的向量）及 Markdown 阅读版。
- 用户要求排除标题为“pco初始化失败”的经验。原先按完整标题、忽略英文大小写及首尾空格的过滤未命中；随后在本地 JSONL 中用 PowerShell 搜索 pco，确认以下三条标题均显示为“pco初始化失败”。未命中的原因尚未验证，PowerShell 向 Python 管道传递中文时的编码变化只是可能原因。
- 最终按下列已确认 ID 从本地文件排除，保留原始导出文件，另生成过滤版。用户回传 **`EXPORT_OK / EXCLUDED: 3 / EXPORTED: 30`**，脚本已核验输出 30 条、ID 唯一及三个排除 ID 不在结果中。这里只过滤导出文件，线上三条经验未删除。

排除的经验 ID：

- `tracefix_007dfb21ebed4ed5da022fa5e5b188b5d477a1244628e3cc`
- `tracefix_4eaee544cc4f81b7fe2ddc72d1745b8d73149bf68cc3434f`
- `tracefix_e2045a978d6d4b4c68dcf320e95e217ec991b6ad6cece125`

文件目录：`D:\agent-memory\AgentMemory\exports\UPCF_20261022_114414_275069\`

| 文件 | 用途 |
| --- | --- |
| `UPCF_experiences.jsonl`、`UPCF_experiences.md` | 初始 33 条，保留原文件 |
| `UPCF_experiences_filtered.jsonl` | 最终 30 条完整数据，后续提取以此为准 |
| `UPCF_experiences_filtered.md` | 最终 30 条阅读版 |

上述数量是 10 月 22 日查询时的已入库快照，不代表当前实时数量，也不能据此认定重建任务已追平。

**线上 Mapping 与连接检查：**

- 用户回传 Mapping 请求返回 200：`product.product_name`、`product.pdu_name`、`product.pdu_code`、`product.version_name` 均为 keyword。
- `product.product_id` 为 text，带 `keyword` 子字段（`ignore_above=256`）；直接按产品 ID 精确查询应使用 `product.product_id.keyword`，共用过滤代码可通过已有 `EXPERIENCE_PRODUCT_ID_FIELD` 配置适配。本轮未修改该配置。
- `title` 为 text，使用 `ik_max_word_analyzer` 和 `ik_smart_analyzer`，无 keyword 子字段；本次取回后在本地排除，避免对分词字段直接使用 term 判断完整标题。
- 初次 Mapping 查询虽选对正式索引，但返回 401。指导在同一 PowerShell 窗口检查或重新设置有效 `CRE_KEY` 后，用户回传查询成功；未记录密钥，未进一步确认认证失败根因。Pydantic 与 HTTPS 警告不是该次 401 的直接诊断依据。

**用例编号保存位置与提取：**

- 核查 `memory_service/trace_experience_pipeline.py` 的 `build_body()`：代码把 `'来源用例：' + step['caseId']` 固定追加到经验正文的 Debug Trace 中，不依赖模型生成该来源行。
- ES 的 `metadata` 未单独保存 `case_id`；用户回传样本元数据包含 source、group_id、fix_step_id、source_revision、failure_phenomenon、related_step_ids、payload_hash，没有用例编号。`fix_step_id` 是修复步骤 ID，不能当作用例编号。
- `db_operate/trace_experience_store.py` 的 `discover()` 将上游用例编号独立保存到 SQL `trace_experience_record.case_id`。
- 已给出从过滤版 JSONL 的 `_source.experience` 按 `(?m)^来源用例：[ \t]*([^\r\n]+)` 提取的 PowerShell 命令：每条经验对应一行，保留重复用例，匹配数不是 1 时输出经验 ID 供核查。30 条经验不等于 30 个不同用例。
- 用户后续在 Excel 中处理 `1. Network_SCP_N5_01_04` 这类带序号的文本；公式报计算错误后，已指导按空格分列得到用例编号。未收到完整 30 行编号或唯一用例数，不记录为已核验的完整用例清单。本轮未新增 ES 用例编号字段。


## 8. experience-engine skill

### 8.1 已确认并实现的行为

skill 位于 `skills/experience-engine/`，供 Agent 在失败分析和修复过程中检索历史经验。已删除 skill 的存入能力及 `scripts/save_experience.py`，仅保留检索；服务端经验提取、新建、覆盖和删除流程仍按前述规则运行。

| 文件 | 作用 |
| --- | --- |
| `skills/experience-engine/SKILL.md` | 通用调用协议、配置读取流程和输出要求 |
| `skills/experience-engine/references/experience-guide-testdebug.md` | 测试脚本调测场景、可选产品名称、检索时机和关键词来源 |
| `skills/experience-engine/scripts/search_experience.py` | 构造检索请求、自动获取调用人工号、打印结果 |

配置与请求规则：

- 场景配置为 `scene_id=421`；当前脚本的默认场景为空，实际调用必须从 reference 读取并传入场景，否则报错。
- 产品使用名称 `product_name`，不使用产品 ID；reference 默认配置为 `""`，表示不限制产品。
- 产品名称未配置、未传、为空字符串或仅含空格时，省略 CLI 的 `--product-name`；脚本也会归一化空值，并省略请求中的整个 `product` 字段。
- 产品名称非空时，使用经验库中实际存储的完整名称，传入 `--product-name`；请求字段为 `product.product_name`。这不改变服务端入库时保存 `groupId/groupName` 的规则。
- 本次需求最终确认为“产品可选”，未新增产品版本参数或配置。
- 调用人工号通过 `getpass.getuser()` 自动获取并填入 `caller_id`，无需手工传参；获取失败或为空时报错。运行环境的用户名应为实际工号。
- 默认不附加 `user_id`，检索同场景下各用户的经验；Python 函数保留显式 `user_id` 参数供兼容调用，CLI 不暴露该参数。

脚本调用 `POST https://fuyao.rnd.huawei.com/memory/experience/doc/search`，使用 `search_field=rag_search_text`、`top_k=5`、`score_threshold=0.3`，请求超时 30 秒。脚本使用 Python 标准库，不需要安装服务端依赖。

reference 是 Agent 读取的业务配置，**脚本不会自动解析 Markdown reference**。Agent 读取后组装参数；手工运行脚本时，需要自行传入场景和可选产品名称。

测试脚本调测场景要求进入 Step 2 失败原因分析时先检索；Step 4 修复验证出现不同的新报错时重新检索。关键词来自核心 ERROR 日志、脚本文件名、相关类名/函数名/模块名。结合 Error Log、Root Cause 和 Pattern 判断适用性，采用 Diff 前核实当前版本。

输出必须原样保留【经验检索输入】【经验检索返回】【原始返回 JSON】三段。返回 `code=200` 时退出码为 0，否则为 1；不得编造或改写召回结果。

### 8.2 自动发布开发包

流水线为 `.github/workflows/publish-experience-engine.yml`：

- 每次 push 到 `develop` 都触发，无路径过滤；仅更新文档也会触发。
- 对触发提交中的 `skills/experience-engine` 执行 `git archive`，产物为 `experience-engine.zip`，解压根目录为 `experience-engine/`。
- 打包范围仅为该 skill 的已提交文件，不包含服务端代码。
- 每次创建独立 GitHub prerelease，标签格式为 `experience-engine-develop-<run_number>.<run_attempt>`，保留历史版本，不标记为正式 Latest。
- 从 [Releases](https://github.com/yf990848-droid/experience/releases) 下载所需版本的 ZIP；解压至项目 `.opencode/skills/`，得到 `.opencode/skills/experience-engine/SKILL.md`。

本轮对话中已确认成功的发布为 [experience-engine-develop-2.1](https://github.com/yf990848-droid/experience/releases/tag/experience-engine-develop-2.1)，对应提交 `6343876f1c09cf85fe3b61221daa42fccaad23f0`，包含产品可选行为。此处是已验证版本记录，不代表后续最新版本。

### 8.3 本地验证方法与状态

在可访问上述内网接口的电脑上，以 Windows PowerShell 为例，从安装 skill 的项目根目录执行：

```powershell
python --version
python -c "import getpass; print(getpass.getuser())"

$experienceSearch = ".opencode\skills\experience-engine\scripts\search_experience.py"
$experienceQuery = "替换成已入库经验中的实际错误关键词"

# 不传产品
python $experienceSearch $experienceQuery "421"
$LASTEXITCODE

# 空字符串，使用等号写法避免 PowerShell 丢弃空参数
python $experienceSearch $experienceQuery "421" --product-name=
$LASTEXITCODE

# 纯空格
python $experienceSearch $experienceQuery "421" --product-name "   "
$LASTEXITCODE

# 指定经验库中实际存储的产品名称
python $experienceSearch $experienceQuery "421" --product-name "实际产品名称"
$LASTEXITCODE
```

检查自动获取的用户名是否为实际工号。前 3 种产品输入应显示“不限制产品”，第 4 种应显示指定名称。检查三段输出是否完整、原始 JSON 的 `code` 是否为 200、退出码是否为 0；指定产品时，结合原始返回数据或已知经验核对产品范围。`code=200` 且结果为空仅说明请求成功，召回效果需使用已知入库经验验证。

Agent 端到端验证：先将 reference 的产品名称留空，请 Agent“使用 experience-engine，按测试脚本调测 reference 检索历史经验，关键词为实际错误关键词，展示实际调用命令和脚本三段输出，本次只验证检索”。检查其读取 reference、传入场景、未附加产品参数，并实际执行脚本。随后填写真实产品名称重试，检查命令是否追加 `--product-name`。

此前已完成模拟网络请求下的产品未传、空字符串、纯空格和指定名称验证，以及函数缺省/None 输入、场景缺失提示、原始结果保留、skill 格式和差异检查；开发包发布流水线已成功执行。**本次对话尚未收到用户本地验证结果，skill 的真实内网接口连通性及 Agent 端到端调用仍待验证**；前述服务端试运行记录不能替代这些验证。

### 8.4 相关提交

- `0b457b724086f0e72803ce2b9b601f62cc6fdb44`：skill 改为仅检索，按产品名称配置，自动获取调用人工号。
- `87cd5181db7ad96c815da480bcca83cbf134d458`：增加 develop 自动发布 skill ZIP 的流水线。
- `6343876f1c09cf85fe3b61221daa42fccaad23f0`：产品名称改为选填，空值省略整个 product 字段，同步 skill、reference 和发布说明。

## 9. 后续跟踪

1. 根据 7.4 已回报的游标位置持续检查新任务推进，取得最新汇总（created/updated/failed/has_more）及 pending/failed 数量，确认是否追平；抽查新经验的 `product.product_name`、原始 Diff 和修复点时间，确认旧任务不再运行。追平后沿用当前任务自动增量，跟踪积压续跑和失败重试。定时任务运行期间不要并行手动补跑。
2. 继续核实上游 Diff 基线问题及 9 月 13 日之后数据质量；本轮仅清理了 7.2 所述 ES 当前经验，旧 SQL 状态与上游坏数据未清理。另行跟踪模型输出失败记录。
3. 若 CodeCheck 再报版本级任务占用，待占用任务结束后重跑并查看真实检查结果。
4. 接口将来提供可直接使用的 `product` 字段时，再核对类型与 ES Mapping 并补充 `metadata.product`。

5. 完成 experience-engine 的内网脚本验证和 Agent 端到端验证，记录实际返回及产品过滤结果。

6. 跟进 7.3 的旧经验缺失样本：核实 Step `1327580` 当前更新时间及新任务处理记录，区分范围过滤、尚未处理、处理失败和检索未召回；目前仅确认备份中的修复时间为 9 月 6 日，未授权恢复或扩大重跑范围。

## 10. 关键文档

- [调测轨迹经验提取设计文档](./调测轨迹经验提取设计文档.md)
- [调测轨迹经验提取最简方案](./调测轨迹经验提取最简方案.md)
- [调测轨迹经验提取最简实现方案](./调测轨迹经验提取最简实现方案.md)
- [经验管理 API 文档](./经验管理%20API%20文档.md)
- [experience-engine 使用说明](../skills/experience-engine/SKILL.md)
- [测试脚本调测检索配置](../skills/experience-engine/references/experience-guide-testdebug.md)
- [skill 开发包发布流水线](../.github/workflows/publish-experience-engine.yml)
