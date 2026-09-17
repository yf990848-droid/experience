# 脚本调测轨迹经验提取项目上下文

更新时间：2026-09-17  
维护分支：`develop`；发布分支：`main`

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

- `Debug Trace`：上次失败、本次修改、修改后结果，并保存真实 `testUser` 和来源 Step；
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

正式配置位于 `TASK_RUNNER_CONFIG['TRACE_EXPERIENCE_EXTRACT']`：`enabled=True`，任务名 `trace_experience_prod_20260501`，北京时间从 `2026-05-01 00:00:00` 开始、结束时间为空；每天增量运行一次。仍有历史积压时，一轮完成后最多等待 60 秒继续有界处理；本服务按单实例运行。

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
- 模型请求失败、格式错误、证据不足或结果未知：保留已有经验并等待重试。

失败现象用于经验标题、正文和检索，不参与 `doc_id` 计算，也不用于覆盖其他轨迹的经验。

## 6. SQL 状态设计

### 6.1 `trace_experience_job_state`

记录整个任务读到哪里，核心字段是 `last_update_time + last_id`。服务重启后从该位置继续读取。

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
- 另一次单轮结果为 `discovered=3`、`completed=1`、`failed=2`、`has_more=True`；失败对应历史数据的 `JSONDecodeError`、`TypeError`，已决定暂不清理旧数据。`has_more=True` 表示还有增量页待处理。
- 本地针对 `test_trace_experience_pipeline.py` 的离线测试已通过；测试使用模拟接口、模型、ES 和 SQLite，不代替生产环境连接验证。测试桩已覆盖模型重试窗口，验证部分批次失败时保留先前完成的修复。
- ES 按固定 `doc_id` 查询返回 404 表示此前不存在该经验，新建前出现属于正常现象；模型输出不完整时记录具体错误，已完成的结果可重试复用。
- 2026-09-17 一次 CodeCheck 任务因同项目版本级检查同时运行而未能创建（`CC.10010253.400`），后续报告缺失是连带结果；该日志没有给出源码检查结论。需在占用任务结束后复验流水线。

## 8. 后续跟踪

1. 核实正式服务持续运行时的每日增量、积压续跑和历史失败重试；单轮 `--once --max-pages 1` 可用于定位，不会启动其他定时任务。
2. 另行处理既有坏数据及模型输出失败记录；避免为排障清空或覆盖已有经验引用。
3. 若 CodeCheck 再报版本级任务占用，待占用任务结束后重跑并查看真实检查结果。
4. 接口将来提供可直接使用的 `product` 字段时，再核对类型与 ES Mapping 并补充 `metadata.product`。

## 9. 关键文档

- [调测轨迹经验提取设计文档](./调测轨迹经验提取设计文档.md)
- [调测轨迹经验提取最简方案](./调测轨迹经验提取最简方案.md)
- [调测轨迹经验提取最简实现方案](./调测轨迹经验提取最简实现方案.md)
- [经验管理 API 文档](./经验管理%20API%20文档.md)
