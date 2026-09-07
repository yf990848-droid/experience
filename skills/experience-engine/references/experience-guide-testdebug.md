# 测试脚本调测 — 经验中心配置

本文件配置"测试脚本调测"场景下的经验检索和存入业务规则。
通用调用协议(脚本路径、参数格式、固定临时文件路径)见 experience-engine 的 SKILL.md,本文件只关注**本场景下要传什么值**。

---

## 一、基本信息

| 配置项 | 内容 |
|--------|------|
| 场景名称 | 测试脚本调测经验 |
| scene_id | 421 |
| scene(存入时传 `--scene`) | 测试脚本调测经验 |

---

## 二、检索经验配置

| 配置项 | 内容 |
|--------|------|
| 什么时候检索 | 1. 进入 Step 2 失败原因分析时,第一个动作必须检索;2. Step 4 修复验证循环中,出现与上一轮不同的新报错时,必须重新检索 |
| 关键词信息来源 1 | 错误日志中的 ERROR 级别关键报错信息(去掉时间戳、进程号等噪音) |
| 关键词信息来源 2 | 脚本文件名 |
| 关键词信息来源 3 | 报错涉及的类名、函数名、模块名 |
| "有用"的判断条件 | 经验中的 error_log 与当前报错特征一致或高度相似;或 Pattern 的触发场景与当前问题匹配;或 root_cause 与当前分析方向一致 |

---

## 三、存入经验配置

| 配置项 | 内容 |
|--------|------|
| 什么时候存入 | 1. 修复成功并同步到正式文件后;2. 达到重试上限需请求人工介入时;3. 问题定界为产品/环境问题需请求人工介入时;4. 任何退出路径都必须先存入经验再结束任务 |
| title 生成规则 | 一句话概括本次经验的核心问题,如"xxx导致xxx失败"(固定规则,无需修改) |
| summary 生成规则 | 2-3 句话说明:涉及什么 + 核心问题 + 最终解决方案(固定规则,无需修改) |
| experience 小节 1 | 名称:error_log;要求:列出调试中遇到的所有关键错误日志行,去掉时间戳、进程号等噪音,保留报错特征 |
| experience 小节 2 | 名称:root_cause;要求:归一化原因分析,如果解决了多个问题则分点描述 |
| experience 小节 3 | 名称:Pattern;要求:核心复用规则,格式 `[触发场景] -> [修复动作]` |
| experience 小节 4 | 名称:Debug Trace;要求:按时间顺序记录完整修改过程,最后以"最终修复结果"收尾 |
| experience 小节 5 | 名称:Diff;要求:最终修复的代码 diff 块。如果本次未修改脚本(如定界为产品/环境问题请求人工介入),此小节写"无需修改脚本,原因:<简述>"即可,禁止直接省略该小节 |
| rag_search_text 关键词来源 1 | 从 error_log 中提取报错特征词 |
| rag_search_text 关键词来源 2 | 从 root_cause 中提取根因关键词 |
| rag_search_text 关键词来源 3 | 从 Pattern 中提取触发场景词 |
| rag_search_text 关键词来源 4 | 脚本文件名 |
| rag_search_text 关键词来源 5 | 涉及的类名、函数名、模块名 |

---

## 四、完整调用示例(本场景)

### 检索

```
python .opencode/skills/experience-engine/scripts/search_experience.py \
  "SET AFRATTYPECFG 错误码 100017 MML命令 N5RATPARA" \
  "421"
```

### 存入

**第 1 步**:把 experience 的 Markdown 内容写入固定临时文件 `.opencode/skills/experience-engine/.experience_tmp.md`:

````markdown
## error_log
预期返回错误码 100017,实际返回错误码 100015

## root_cause
测试脚本预期错误码与实际产品行为不一致。产品将所有非法参数值(包括 N5RATPARA=2)统一返回错误码 100015,而非区分不同非法值返回不同错误码。

## Pattern
[MML命令非法参数值] -> [修正预期错误码为产品实际返回的错误码]

## Debug Trace
1. 执行 MML 命令 `SET AFRATTYPECFG: AFIFTYPE=N5, N5RATPARA=2`
2. 检查返回结果,发现错误码为 100015
3. 对比测试脚本预期错误码 100017
4. 确认产品实际行为是将非法值统一返回 100015
5. 修改第 157 行将 Resultcode 从 100017 改为 100015
6. 验证通过

最终修复结果:测试脚本通过,预期错误码与产品行为一致。

## Diff
```diff
- Resultcode="100017"
+ Resultcode="100015"
```
````

**第 2 步**:执行存入命令:

```
python .opencode/skills/experience-engine/scripts/save_experience.py \
  --title "MML命令参数错误码预期错误导致测试失败" \
  --summary "测试脚本执行 SET AFRATTYPECFG 命令时预期返回 100017,实际产品返回 100015,修改预期值为 100015 后通过。" \
  --rag "SET AFRATTYPECFG 错误码 100017 100015 MML命令 参数非法值 N5RATPARA 测试脚本" \
  --scene-id "421" \
  --scene "测试脚本调测经验" \
  --experience-file ".opencode/skills/experience-engine/.experience_tmp.md"
```

---

## 五、注意事项

| 序号 | 内容 |
|------|------|
| 1 | 检索时优先关注 Pattern 字段,因为它直接提供 `[触发场景] -> [修复动作]` 的复用规则 |
| 2 | 如果同一脚本有历史经验,优先级最高——说明同一脚本之前调试过 |
| 3 | Diff 字段可以直接作为修复参考,但需验证是否适用于当前版本 |
| 4 | error_log 中保留具有泛化特征的报错信息,提高未来检索准确度 |
| 5 | rag_search_text 要尽量丰富,关键词越全面越好 |
| 6 | 存入失败时静默跳过,不影响主流程 |
