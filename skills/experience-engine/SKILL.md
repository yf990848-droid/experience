---
name: experience-engine
description: 通用经验中心工具,提供经验检索与经验存入两个原子能力。具体业务场景(检索时机、关键词来源、字段生成规则等)通过 references/experience-guide-<场景名>.md 配置。
---

# Experience Engine

经验中心工具,用于在各类任务流程中**检索历史经验**和**沉淀本次经验**。

本 skill 本身不规定"什么时候用、关键词怎么提、字段怎么写"——这些是**业务规则**,由各场景的 `references/experience-guide-<场景名>.md` 配置。SKILL.md 只负责告诉 agent:**两个操作怎么调用**。

---

## 1. 两个原子能力

| 能力 | 脚本 | 说明 |
|------|------|------|
| 检索经验 | `scripts/search_experience.py` | 输入 query + scene_id,返回最相关的若干条历史经验 |
| 存入经验 | `scripts/save_experience.py` | 把本次调试/任务的经验写入经验中心 |

**两个操作的业务规则必须读对应的 `references/experience-guide-<场景名>.md` 获取**,不要凭记忆拼参数。

---

## 2. 调用协议

### 2.1 检索经验

```
python .opencode/skills/experience-engine/scripts/search_experience.py "<query>" "<scene_id>"
```

- `<query>`:按 experience-guide 的"关键词信息来源"拼装,空格分隔
- `<scene_id>`:从 experience-guide 的"基本信息"读取

脚本会输出【经验检索输入】【经验检索返回】【原始返回 JSON】三段内容。**原样保留这三段输出**作为分析依据,禁止自行编造或改写召回结果。

### 2.2 存入经验

**两步操作**,统一使用固定路径 `.opencode/skills/experience-engine/.experience_tmp.md` 作为 experience 的临时文件——跨 shell(bash / Git Bash / PowerShell / cmd)通用,无需处理平台差异。

**第 1 步:把 experience 的 Markdown 内容写入固定临时文件**

文件路径(项目根目录下的相对路径,**所有场景、所有 shell 都用这一个**):
```
.opencode/skills/experience-engine/.experience_tmp.md
```

文件内容是 experience 的完整 Markdown——按 experience-guide 的小节定义组织好即可,**不需要任何转义**。

**第 2 步:执行存入命令**

```
python .opencode/skills/experience-engine/scripts/save_experience.py \
  --title "<title>" \
  --summary "<summary>" \
  --rag "<rag_search_text>" \
  --scene-id "<scene_id>" \
  --scene "<scene>" \
  --experience-file ".opencode/skills/experience-engine/.experience_tmp.md"
```

执行完成后该临时文件可保留或覆盖,不影响下次使用。

**参数说明**

| 参数 | 必填 | 来源 |
|------|------|------|
| `--title` | 是 | 按 experience-guide 的 title 生成规则生成 |
| `--summary` | 是 | 按 experience-guide 的 summary 生成规则生成 |
| `--rag` | 是 | 按 experience-guide 的 rag_search_text 关键词来源汇总 |
| `--scene-id` | 是 | 从 experience-guide 的"基本信息"读取 |
| `--experience-file` | 是 | **固定为 `.opencode/skills/experience-engine/.experience_tmp.md`** |
| `--scene` | 否 | 从 experience-guide 的"基本信息"读取 |
| `--user-id` | 否 | 默认取 `$USERNAME` 环境变量,一般无需手动传 |

---

## 3. 为什么用固定相对路径而不是系统临时目录

experience 内容几乎一定包含双引号、反引号、美元符、代码块、多行文本等特殊字符,**必须通过文件传入**避免 shell 解析出错。

不用 `%TEMP%`、`$TMPDIR`、`/tmp` 等系统临时目录的原因:
- `%TEMP%` 只在 cmd/PowerShell 下展开,Git Bash 不认
- `/tmp` 在 Windows 原生 shell 下不存在
- 跨平台绝对路径需要 agent 判断操作系统,容易出错

**统一用项目内的固定相对路径**,所有 shell 照抄同一条命令即可。该文件位于 skill 自己的目录下,可在 `.gitignore` 中忽略。

---

## 4. 使用流程(agent 视角)

**检索时**:
1. 读取对应场景的 `references/experience-guide-<场景名>.md`
2. 按"检索经验配置"中的关键词来源构造 query
3. 调用 `search_experience.py`
4. 按"有用的判断条件"评估召回结果,决定是否采用

**存入时**:
1. 读取对应场景的 `references/experience-guide-<场景名>.md`
2. 按各字段的生成规则提取/组织本次经验内容
3. 把 experience 的 Markdown 内容写入固定路径 `.opencode/skills/experience-engine/.experience_tmp.md`
4. 调用 `save_experience.py`,`--experience-file` 传入同一路径
5. 存入失败时静默跳过,不影响主流程;但应在日志中保留返回信息

---

## 5. 当前支持的场景

| 场景名 | 配置文件 | 说明 |
|--------|---------|------|
| 测试脚本调测 | `references/experience-guide-testdebug.md` | 测试用例脚本执行失败的调试经验 |

新增场景时,只需在 `references/` 下添加一份 `experience-guide-<场景名>.md`,按现有格式填写即可,无需修改本 SKILL.md 和脚本。
