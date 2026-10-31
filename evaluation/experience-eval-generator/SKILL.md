---
name: experience-eval-generator
description: 根据选定的 UPCF 调测经验 JSONL，在本地 Cases 中寻找同目录其他用例并注入同类错误，生成用于经验检索和脚本修复评测的候选集。当用户要求从历史经验构造新故障用例、生成评测脚本或按配置批量构造评测集时使用。路径从 reference 读取；仅生成与静态校验，不执行远程测试。
---

# 经验评测集生成

## 初始化

1. 读取 [upcf-evaluation.md](references/upcf-evaluation.md) 中配置、业务规则和决策文件契约。
   experience_jsonl 为空时，请用户填写实际生成文件的路径，不猜测时间戳目录。
2. 以本 skill 的实际安装位置为基准运行（Python 3.9+，仅标准库）：
   `python <skill目录>/scripts/prepare_evaluation.py init`
   可通过 `--reference <路径>` 读取另一个采用相同结构的 reference。
3. 读取打印的运行目录下 evaluator/manifest.json。它包含输入快照、提交号、工作区状态、
   Cases 文件哈希、全部 23 条经验、来源定位结果及同目录候选路径。
   不修改 manifest 的初始化字段。若工作区不干净，如实记录；不得清理用户修改。
4. 读取源仓库根目录和涉及路径上的 AGENTS.md。严格只读源仓库；只在本次输出目录写文件。

## 逐条分析并生成

按 sequence 遍历全部任务，持续写 evaluator/decisions.json 以保留进度。
不要把辅助脚本 init 当成任务完成；必须继续逐条选候选、生成、校验及汇总。

1. 阅读该条 experience 的 Error Log、原始 Diff、Root Cause、Pattern，并查看当前来源脚本。
   不认为当前源码就是历史失败版本，不把根因推断当作已证实事实。
2. 来源不唯一或不存在时记录阻塞。来源明确时只检查 manifest 列出的同目录其他脚本。
   从真实测试用例中挑选适合的母本；排除辅助模块、来源脚本的仅改名副本和已用母本。
   比较业务流程、调用、检查字段、参数及触发前提，不能仅凭文件名或代码相似度选择。
   必要时只读核查 reference 指定的 AW 和配置，记录源码位置和适用理由。
3. 确定一个可迁移错误机制。反向 Diff 仅为线索，不机械复制历史业务值。
   不通过 raise、无关断言或改公共 AW 伪造故障；不削弱必要业务检查或清理流程。
   有证据不足、当前版本不适用、候选自身不合规时，尝试其他候选；仍不成立则报告阻塞。
4. 为候选分配不冲突的新标识，例如 `<母本CaseID>_EVAL_<新序号>`，核查仓库命名规则。
   将母本旧标识统一替换为新标识，生成 evaluator/staging/NN/baseline.py。
   此基线仅表示注入前代码，不代表已运行通过。基线不允许其他修改。
5. 从基线生成 evaluator/staging/NN/faulty.py。只注入目标故障，必要的关联位置一起修改。
   保留完整脚本、编码、导入、预置、清理及日志备份。文件名、类名、CaseID 在最终产物中一致。
   不在脚本里写目标经验 ID、故障解释或参考修复；原有正常业务注释可以保留。
6. 人工语义核查注入是否可达、PCO/BAW/清理和业务检查是否合理、没有引入其他独立故障。
   检查母本选择和新标识是否重复，记录检查事实及不能验证的部分。
7. 按 reference 契约写 ready 或阻塞决策，记录选择、注入、预期现象和验收依据。
   不声称模拟日志为实测结果，不将 executeResult=FAIL 的历史记录宣称为完整成功证明。

## 校验与发布

所有 23 条均有决策后执行：
`python <skill目录>/scripts/prepare_evaluation.py finalize --run-dir <本次目录>`

脚本核对源仓库快照、决策覆盖、候选资格、母本/新标识唯一性、基线仅重命名、Python 语法、
类名/CaseID 和必要结构，并生成故障脚本、基线、正反补丁、manifest 和 report。
静态失败项会保留原因，不冒充生成成功。脚本不能自动证明 AW 语义、触发可达性或运行效果，
必须保留模型核查记录，不能把它作为运行验收替代。

输出：
- evaluation_cases/：保留 Cases 内相对目录结构的故障脚本，仅此部分交给后续被测 Agent。
- evaluator/baselines/：使用新标识的注入前脚本。
- evaluator/patches/：注入差异及参考逆向修复差异；其他有效修复不要求逐字等于该补丁。
- evaluator/manifest.json、report.md：逐条映射、依据、状态和阻塞原因。
- evaluator/staging/、decisions.json：生成过程材料，包含答案，不交给被测 Agent。

运行中断时继续本次 staging 和 decisions；源仓库变化或结果已发布后重新 init，不覆盖旧结果。
汇总总数、成功生成数、各阻塞项及输出路径，明确所有生成项为“待运行验证”。
后续应在独立会话中评测，隔离 evaluator 和输入经验文件；不自动运行 coretest_run.py。
