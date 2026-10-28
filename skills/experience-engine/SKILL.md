---
name: experience-engine
description: 通用经验检索工具，用于任务失败分析和修复过程中查询历史经验。具体业务场景的检索时机、关键词来源、场景和产品名称通过 references 中各场景的经验指南配置。
---

# Experience Engine

读取对应场景的 `references/experience-guide-<场景名>.md`，获取业务配置，再调用检索脚本。仅检索，不上传经验。

## 1. 安装与首次登录

完整发布包包含 `scripts/search_experience.py` 和 `scripts/coreinsight-cli.exe`，适用于 Windows；运行脚本需要 Python 3.9+，无需安装第三方 Python 依赖。将 skill 安装到项目 `.cac/skills/experience-engine/`。

首次使用前，请用户在本地终端登录，替换 `<工号>`，按提示输入密码。

CMD：

```cmd
".cac\skills\experience-engine\scripts\coreinsight-cli.exe" auth login --username <工号>
```

PowerShell：

```powershell
& ".cac\skills\experience-engine\scripts\coreinsight-cli.exe" auth login --username <工号>
```

CLI 自动保存和复用用户目录下的登录会话。调用人工号取登录工号，不从系统用户名获取。会话失效时提示用户重新登录；不要自动发起交互式登录，不收集或保存密码，不把会话文件打包。

## 2. 调用协议

以下示例从项目根目录执行；安装位置不同时使用实际脚本路径。脚本按自身位置查找同目录 exe，不依赖当前工作目录或 PATH。

```cmd
python .cac\skills\experience-engine\scripts\search_experience.py "<query>" "<scene>"
```

| 参数 | 来源 |
|------|------|
| `<query>` | 按场景 reference 的“关键词信息来源”拼装，空格分隔 |
| `<scene>` | 从场景 reference 的 `scene` 读取场景名称，不传场景 ID |
| `--product-name` | 选填，从 reference 的 `product_name` 读取实际完整产品名称 |

产品未配置、为空字符串或仅含空格时省略 `--product-name`，不限制产品；非空时脚本映射为 CLI 的 `--products`。不使用示例占位符作为产品名称。

脚本调用同目录 CLI 的 `experience search`，固定传 `--search_field rag_search_text --page 1 --page_size 5`，场景名称传 `--scene`。默认不传 `--user_id`，检索同场景下各用户的经验。阈值和排序上限沿用 CLI/服务端行为，不设置固定阈值、不在本地二次过滤。请求超时 120 秒，子进程等待上限 130 秒。

## 3. 使用流程与输出

1. 读取场景 reference，获取场景名称和可选产品名称。
2. 按关键词来源构造 query，实际执行检索脚本。
3. 原样保留【经验检索输入】【经验检索返回】【原始返回 JSON】三段输出。原始 JSON 为 CLI 完整 JSON-RPC 返回，禁止编造、裁剪或改写召回结果。
4. 按 reference 的“有用的判断条件”判断是否采用；请求成功不代表经验适用。

CLI 退出码为 0、无 error 且 result.code=200，并返回有效 data.items 时视为成功，空数组也是成功。未登录返回非零退出码并显示登录命令；exe 缺失提示安装包不完整；其他错误明确报错，不当作无经验处理。

## 4. 当前支持的场景

| 场景名 | 配置文件 | 说明 |
|--------|---------|------|
| 测试脚本调测 | `references/experience-guide-testdebug.md` | 测试用例脚本执行失败的调试经验 |

新增场景时，在 `references/` 下添加经验指南，填写场景名称、检索时机和关键词来源，按需配置产品名称。reference 由 Agent 读取，脚本不会自动解析 Markdown。
