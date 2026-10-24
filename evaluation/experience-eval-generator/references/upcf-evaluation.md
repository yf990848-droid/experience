# UPCF 评测集配置与约束

修改下面唯一 JSON 块。experience_jsonl 填入 prepare_upcf_evaluation.py 生成的
UPCF_evaluation_experiences_23.jsonl 完整路径；不能填原始 30 条 ES 导出文件。
输出目录与源仓库分离。辅助脚本直接读取此配置，不需要用户每次传路径。

```json
{
  "repository_root": "D:\\UPCFTestcases",
  "cases_root": "D:\\UPCFTestcases\\Cases",
  "experience_jsonl": "D:\\agent-memory\\AgentMemory\\exports\\UPCF_20261022_114414_275069\\evaluation_input_20261024_164907_030738\\UPCF_evaluation_experiences_23.jsonl",
  "output_root": "D:\\UPCF-evaluation-output",
  "expected_count": 23,
  "candidate_scope": "same_directory",
  "readonly_reference_paths": [
    "D:\\UPCFTestcases\\UserFiles\\Logic",
    "D:\\UPCFTestcases\\UserFiles\\Config"
  ]
}
```

## 仓库规则

- Cases 是唯一用例来源。来源脚本的直接父目录是候选范围，不递归扩展至相邻目录。
- 只读源仓库。按需阅读 UserFiles/Logic 中相关 AW 和 UserFiles/Config 中相关配置。
- 读取根目录及来源、候选、参考文件路径上的适用 AGENTS.md；子目录规则同样有效。
- 新文件名、类名、information.CaseID 一致。保留 CaseName、Level、CloudSpider 继承、
  Precondition、Procedure、Failure、Postcondition，以及 Failure 的 BackUpDebugLog。
- 保留初始化、资源清理和业务检查。新增调用只允许仓库规范允许的 BAW，不新建 AW。
- 核查 PCO 使用/初始化一致性、动态用户组参数及会话下线；静态脚本不能证明这些业务规则成立。
- 新增或修改的步骤描述使用 logger.step()，不新增 # STEP:。不能添加提示答案的注释或 AI 占位备注。
- 避免 while。保留 GLB、PMS、配置占位符和候选业务数据；不搬入历史用例的特定标识。
- 指南中的 CloudSpider: 继承示例是语法错误；方法使用 Procedure，不能照搬 procedure。
- 候选本来不合规时记录或换候选，不顺手全面整改。

## 本次范围

尝试全部 23 条，不因 quality、历史 executeResult=FAIL 或修复证据不完整提前过滤。
但是否能生成取决于当前源码和场景证据；无证据则逐项报告，不强行补足数量。
同一批次不得重复使用母本；禁止以该经验来源脚本或其仅改名副本作为母本。
不要求排除所有其他经验的来源用例，只排除当前经验自己的来源。
不执行远程用例、安装依赖或修改设备，不调用检索 skill 或写入线上经验库。

## decisions.json 契约

在本次目录 evaluator/decisions.json 写 JSON 数组，必须恰好覆盖 sequence 1～23。
成功准备的单项结构如下（这里的路径和名称仅示例，不是真实候选）：

```text
{
  "sequence": 1,
  "status": "ready",
  "candidate": "Cases/模块/OtherCase.py",
  "new_case_id": "OtherCase_EVAL_01",
  "baseline": "01/baseline.py",
  "faulty": "01/faulty.py",
  "selection_reason": "当前候选调用及参数与目标经验的适用条件；列出源码位置",
  "injection_reason": "一个错误机制、修改位置及迁移依据",
  "expected_failure": "预测现象，明确尚未运行；不是历史日志冒充新日志",
  "acceptance": "目标故障消失且原有必要检查保留；后续如何运行验证",
  "manual_checks": "实际完成的业务、PCO、清理、BAW、规范、无答案泄露核查；未确认项如实写出"
}
```

candidate 必须原样使用 manifest 中候选路径（Windows 反斜杠在 JSON 中需转义）。
baseline、faulty 相对于 evaluator/staging；先生成干净基线，再从基线注入错误。
基线严格为母本源码中的旧文件标识替换为新标识，其他内容不变；不适合这种重命名的候选应换选或阻塞。
故障脚本保留基线编码声明，实际文件编码必须匹配。
阻塞单项仅需 sequence、status、reason；status 可为 source_missing、source_ambiguous、
no_candidate、insufficient_evidence、static_failed。详细填写原因和已尝试候选。
