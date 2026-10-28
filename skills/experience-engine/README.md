# experience-engine 使用说明

experience-engine 用于在脚本调测、失败分析和修复过程中检索历史经验，帮助 Agent 参考相关错误、根因和修复方法。当前支持“测试脚本调测经验”场景，仅检索，不写入经验。召回结果是否适用，需要结合当前脚本和实际报错判断。

## 1. 使用前准备

- 使用 Windows，安装 Python 3.9 或以上版本。
- 将完整 Skill 放到项目的 `.cac/skills/experience-engine/` 目录，包内已包含 `scripts/coreinsight-cli.exe`。
- 在项目根目录打开 CMD 或 PowerShell，按下面步骤首次登录。安装位置不同时，将命令中的路径替换为实际路径。

## 2. 首次登录 CLI

将命令中的 `你的工号` 替换为自己的域账号工号。

**CMD：**

```cmd
".cac\skills\experience-engine\scripts\coreinsight-cli.exe" auth login --username 你的工号
```

**PowerShell：**

```powershell
& ".cac\skills\experience-engine\scripts\coreinsight-cli.exe" auth login --username 你的工号
```

出现“密码（输入不回显）”后，输入域账号密码并按回车。输入时看不到字符是正常现象，不要把密码发给 Agent 或写进配置文件。

返回结果中出现 `"authenticated": true` 表示登录成功。登录会话会自动保存，后续检索直接复用，无需每次登录；调用人工号也自动取登录工号。

## 3. 检查登录状态

**CMD：**

```cmd
".cac\skills\experience-engine\scripts\coreinsight-cli.exe" auth status
```

**PowerShell：**

```powershell
& ".cac\skills\experience-engine\scripts\coreinsight-cli.exe" auth status
```

如果提示未登录、会话过期或 `Not Authenticated`，重新执行第 2 节的登录命令即可。

常见问题：
- 提示“此时不应有 &”：当前是 CMD，请使用不带开头 `&` 的 CMD 命令。
- 提示找不到文件：确认终端位于项目根目录，或改用 exe 的完整路径。

## 4. 登录后使用 Skill

在 Agent 中打开安装了 Skill 的项目，例如输入：

> 使用 experience-engine，按照测试脚本调测 reference 检索“ucPreLinkIndex”相关历史经验。本次只检索，不修改代码。

如需限制产品，编辑 [场景配置](references/experience-guide-testdebug.md) 中的 `product_name`，例如填写 `UPCF`；留空则不限制产品。

也可在终端直接验证（CMD、PowerShell 均可）：

```text
python .cac/skills/experience-engine/scripts/search_experience.py "ucPreLinkIndex" "测试脚本调测经验"
```

正常执行会输出“经验检索输入”“经验检索返回”和“原始返回 JSON”三段内容。详细调用规则见 [SKILL.md](SKILL.md)。
