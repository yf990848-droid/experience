---
name: experience-engine
description: 通用经验检索工具，用于任务失败分析和修复过程中查询历史经验。具体业务场景的检索时机、关键词来源、场景和产品名称通过 references 中各场景的经验指南配置。
---

# Experience Engine

读取对应场景的 `references/experience-guide-<场景名>.md`，获取业务配置，再调用检索脚本。

## 1. 检索能力

| 能力 | 脚本 | 说明 |
|------|------|------|
| 检索经验 | `scripts/search_experience.py` | 输入 query、scene_id，可选产品名称，返回最相关的若干条历史经验 |

## 2. 调用协议

```bash
python .opencode/skills/experience-engine/scripts/search_experience.py "<query>" "<scene_id>"
```

需要限制产品时，读取场景 reference 中的产品名称，追加 `--product-name "<product_name>"`。

| 参数 | 来源 |
|------|------|
| `<query>` | 按场景 reference 的“关键词信息来源”拼装，空格分隔 |
| `<scene_id>` | 从场景 reference 的“基本信息”读取 |
| `--product-name` | 选填，从场景 reference 的 `product_name` 读取；有值时与经验库中存储的完整产品名称一致，留空则省略此参数 |

产品名称未传、为空字符串或仅含空格时，请求省略整个 `product` 字段，不限制产品。产品名称非空时，脚本将其放入请求的 `product.product_name`，按场景和产品名称过滤经验。

调用人工号由脚本通过 `getpass.getuser()` 自动获取，并填写请求的 `caller_id`，无需手工配置或传参。运行脚本的系统用户名应为实际工号；获取失败或为空时，明确报错。

默认检索同场景下各用户的经验，请求不自动附加 `user_id` 过滤。

脚本输出【经验检索输入】【经验检索返回】【原始返回 JSON】三段内容。**原样保留这三段输出**作为分析依据，禁止编造或改写召回结果。调用失败时返回非零退出码。

## 3. 使用流程

1. 读取对应场景的 `references/experience-guide-<场景名>.md`。
2. 获取 `scene_id`，读取可选的 `product_name`；产品名称留空则不限制产品，不使用示例占位符作为产品名称。
3. 按“检索经验配置”中的关键词来源构造 query。
4. 调用 `search_experience.py`，传入场景；仅在产品名称非空时追加 `--product-name`。
5. 按“有用的判断条件”评估召回结果，决定是否采用。

## 4. 当前支持的场景

| 场景名 | 配置文件 | 说明 |
|--------|---------|------|
| 测试脚本调测 | `references/experience-guide-testdebug.md` | 测试用例脚本执行失败的调试经验 |

新增场景时，在 `references/` 下添加一份 `experience-guide-<场景名>.md`，填写场景、检索时机和关键词来源，按需配置产品名称。
