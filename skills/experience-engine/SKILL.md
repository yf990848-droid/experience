---
name: experience-engine
description: 通用经验检索工具，用于任务失败分析和修复过程中查询历史经验。具体业务场景的检索时机、关键词来源、场景通过 references 中各场景的经验指南配置，产品名称由脚本从已有调测环境自动获取。
---

# Experience Engine

读取对应场景的 `references/experience-guide-<场景名>.md`，获取业务配置，再调用检索脚本。

## 1. 检索能力

| 能力 | 脚本 | 说明 |
|------|------|------|
| 检索经验 | `scripts/search_experience.py` | 输入 query、scene_id，自动识别产品名称，返回最相关的若干条历史经验 |

## 2. 调用协议

```bash
python .opencode/skills/experience-engine/scripts/search_experience.py "<query>" "<scene_id>"
```

直接调用脚本，无需配置或传递产品名称。

| 参数 | 来源 |
|------|------|
| `<query>` | 按场景 reference 的“关键词信息来源”拼装，空格分隔 |
| `<scene_id>` | 从场景 reference 的“基本信息”读取 |

产品名称由脚本自动获取：复用当前项目已有 Skill 的 `scripts/config.ini` 中 `[envInfo] name`，未配置时读取项目 `.idea/CoreTestPluginSettings.xml` 的 `defaultServerName`。支持 `.opencode`、`.testagent`、`.cac` 安装目录，无需新增配置文件；多个配置中的环境名称不一致时视为识别失败。

脚本仅以环境名称查询环境接口（不传 `creator`），读取 `content.executor.groupId`，再从群组接口匹配 `groupName`，填入 `product.product_name`。识别失败时明确提示，省略整个 `product` 字段并继续不限产品检索。原有 `--product-name` 参数仅保留兼容手动覆盖，正常调用无需传入。

调用人工号由脚本通过 `getpass.getuser()` 自动获取，并填写请求的 `caller_id`，无需手工配置或传参。运行脚本的系统用户名应为实际工号；获取失败或为空时，明确报错。

默认检索同场景下各用户的经验，请求不自动附加 `user_id` 过滤。

脚本输出【经验检索输入】【经验检索返回】【原始返回 JSON】三段内容。**原样保留这三段输出**作为分析依据，禁止编造或改写召回结果。调用失败时返回非零退出码。

## 3. 使用流程

1. 读取对应场景的 `references/experience-guide-<场景名>.md`。
2. 获取 `scene_id`；产品名称由脚本自动识别，无需从 reference 读取。
3. 按“检索经验配置”中的关键词来源构造 query。
4. 调用 `search_experience.py`，传入场景，检查输出中实际使用的产品名称或识别失败提示。
5. 按“有用的判断条件”评估召回结果，决定是否采用。

## 4. 当前支持的场景

| 场景名 | 配置文件 | 说明 |
|--------|---------|------|
| 测试脚本调测 | `references/experience-guide-testdebug.md` | 测试用例脚本执行失败的调试经验 |

新增场景时，在 `references/` 下添加一份 `experience-guide-<场景名>.md`，填写场景、检索时机和关键词来源；产品名称自动获取，无需配置。
