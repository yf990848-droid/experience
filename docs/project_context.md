# 脚本调测轨迹经验提取项目上下文

更新时间：2026-09-11  
当前分支：`develop`

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

无成功修复、没有实际修改、只增加日志或快速失败、修改与故障无关、证据不足的记录不生成经验。当前约定只分析接口直接返回的数据，不下载 `errorCause` 指向的完整日志。

### 2.3 经验内容

经验使用五段式 Markdown：

- `Debug Trace`：上次失败、本次修改、修改后结果，并保存真实 `testUser` 和来源 Step；
- `Error Log`：失败分类行和核心错误；
- `Diff`：只保留与修复直接相关的实际修改；
- `Root Cause`：根据日志和修改说明根因，区分事实和推断；
- `Pattern`：总结触发条件和经过验证的修复动作。

### 2.4 用户和产品

- 云见场景固定为“测试脚本调测经验”，`scene_id=421`。
- `product_id` 暂取字符串形式的 `groupId`。
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

发现轨迹变化后，重新分页读取该组合的全部历史 Step，模型看到的是包含旧数据和新数据的完整轨迹。

响应中的 `diffContent` 和 `customStruct` 是 JSON 字符串，需要再次解析。时间按北京时间处理；`startTime`、`endTime` 是毫秒时间戳。

## 4. 当前实现

核心实现已提交到 `develop`，主要文件包括：

| 文件 | 作用 |
| --- | --- |
| `memory_service/trace_experience_pipeline.py` | 查询 Step、整理轨迹、调用模型、同步经验 |
| `db_operate/trace_experience_store.py` | 建表、保存游标和轨迹处理结果 |
| `db_operate/sql_models.py` | 定义任务状态表和轨迹处理记录表 |
| `project_configs/prompt_configs.py` | 经验提取 Prompt |
| `project_configs/settings.py` | 任务周期、时间范围、接口、模型等配置 |
| `models/llm_caller.py` | 模型请求、超时及安全诊断日志 |
| `api/experience_api.py` | 共用经验创建、覆盖和删除能力 |
| `task_runner.py` | 注册周期任务 |
| `docs/调测轨迹经验提取设计文档.md` | 完整业务和实现设计 |

当前 memory 服务确定为单实例运行，定时任务不增加分布式锁。执行周期可配置，初版每天运行一次。试运行时间范围为北京时间 2026 年 8 月至 9 月。

脚本直接运行时默认初始化新增 SQL 表，也支持显式传入 `--init-tables`。手动小范围验证可使用 `--once --max-pages 1`。

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
- `pending/success/skipped/failed` 状态；
- 重试次数和最近错误；
- 已生成经验的 `doc_id`、`fixStepId`、内容摘要和同步结果。

实际经验正文不保存在这两张表中。

## 7. 当前联调结果

已经确认：

- GaussDB 连接和新增状态表初始化成功；
- CloudSpider 接口可以分页读取数据；
- Elasticsearch 可以访问；
- 模型凭据解密后，简单 Prompt 可以正常返回；
- 模型可能在 `Message` 前输出分析文字并在末尾输出 JSON 数组，解析器已兼容末尾合法数组；
- 模型请求异常或空响应最多重试 3 次；
- 单条轨迹失败不会终止整个任务，任务最终可正常退出。

最近一次运行出现大量：

### 7.1 `invalid_model_array`

模型请求返回了内容，但没有通过经验数组校验。可能包括：

- 没有合法 JSON 数组；
- JSON 被截断；
- 数组类型或字段不正确；
- 返回的修复 Step ID 与请求不一致；
- 多修复点返回数量不一致。

当前日志只显示统一错误名，还不能确认具体是哪项校验失败。

### 7.2 `model_request_failed`

模型网关返回 HTTP 200，但响应只有 26 个字符，外层内容无法按 JSON 解析。连续重试 3 次仍失败后，轨迹记录为 `model_request_failed`。

### 7.3 可忽略或暂不阻塞的问题

- ES 查询固定 `doc_id` 返回 404：表示经验尚不存在，是新建前的正常查询，不是故障。
- `InsecureRequestWarning`：本地关闭 TLS 证书校验产生的警告，不是模型失败原因；正式部署需要配置可信 CA。
- Pydantic `model_id` 命名警告和 GaussDB SQL 缓存警告目前不阻塞功能。
- 汇总中的 `discovered` 只表示本轮新发现数量，`completed/failed` 可能还包含历史待处理记录，因此三者不一定相加相等。

## 8. 当前待办

1. 给 `invalid_model_array` 增加更具体、脱敏的失败原因，例如：无数组、数量不一致、修复 ID 不一致、缺少字段。
2. 对模型网关的短响应增加安全诊断，只记录外层字段名、`Status`、`Message` 是否存在及类型，不打印完整响应。
3. 使用少量真实轨迹复验：
   - 模型返回 `valid=true` 时能够新建经验；
   - 重复运行内容相同则跳过；
   - 轨迹更新后能够覆盖；
   - `fixResult` 失效后能够删除；
   - 证据不足时不创建且不删除已有经验。
4. 上游补充 `product` 字段后写入 `metadata.product`。
5. 正式上线前确认 ES Mapping、TLS CA 和生产配置。
6. 试运行验证稳定后，再扩大处理时间范围。

## 9. 关键文档

- [调测轨迹经验提取设计文档](./调测轨迹经验提取设计文档.md)
- [调测轨迹经验提取最简方案](./调测轨迹经验提取最简方案.md)
- [调测轨迹经验提取最简实现方案](./调测轨迹经验提取最简实现方案.md)
- [经验管理 API 文档](./经验管理%20API%20文档.md)
