---
name: experience-engine
description: 通用经验检索工具，用于任务失败分析和修复过程中查询历史经验。具体业务场景的检索时机、关键词来源、场景和产品名称通过 references 中各场景的经验指南配置。
---

# Experience Engine

读取对应场景的 `references/experience-guide-<场景名>.md`，获取业务配置，再调用检索脚本。

## 1. 检索能力

| 能力 | 脚本 | 说明 |
|------|------|------|
| 检索经验 | `scripts/search_experience.py` | 输入 query、scene_id 和产品名称，返回最相关的若干条历史经验 |

## 2. 调用协议

```bash
python .opencode/skills/experience-engine/scripts/search_experience.py "<query>" "<scene_id>" --product-name "<product_name>"
```

| 参数 | 来源 |
|------|------|
| `<query>` | 按场景 reference 的“关键词信息来源”拼装，空格分隔 |
| `<scene_id>` | 从场景 reference 的“基本信息”读取 |
| `--product-name` | 从场景 reference 的 `product_name` 读取，必填，与经验库中存储的完整产品名称一致 |

脚本将产品名称放入请求的 `product.product_name`，按场景和产品名称过滤经验。产品名称为空时，提示配置缺失并停止本次检索。

调用人工号由脚本通过 `getpass.getuser()` 自动获取，并填写请求的 `caller_id`，无需手工配置或传参。运行脚本的系统用户名应为实际工号；获取失败或为空时，明确报错。

默认检索同场景、同产品下各用户的经验，请求不自动附加 `user_id` 过滤。

脚本输出【经验检索输入】【经验检索返回】【原始返回 JSON】三段内容。**原样保留这三段输出**作为分析依据，禁止编造或改写召回结果。调用失败时返回非零退出码。

## 3. 使用流程

1. 读取对应场景的 `references/experience-guide-<场景名>.md`。
2. 获取 `scene_id` 和 `product_name`；产品名称未填写时，提示补充配置，不使用示例占位符发起请求。
3. 按“检索经验配置”中的关键词来源构造 query。
4. 调用 `search_experience.py`，传入场景和产品名称。
5. 按“有用的判断条件”评估召回结果，决定是否采用。

## 4. 当前支持的场景

| 场景名 | 配置文件 | 说明 |
|--------|---------|------|
| 测试脚本调测 | `references/experience-guide-testdebug.md` | 测试用例脚本执行失败的调试经验 |

新增场景时，在 `references/` 下添加一份 `experience-guide-<场景名>.md`，填写场景、产品名称、检索时机和关键词来源。
