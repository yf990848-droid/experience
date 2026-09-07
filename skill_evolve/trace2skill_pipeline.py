# 标准库
import json
import logging
import re
import sys
import threading
import time
import traceback
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

# 第三方库
import requests

# 应用程序自定义模块
from logger import logger
from project_configs.prompt_configs import ADMISSION_PROMPT_TEMPLATE
from project_configs.settings import (
    ReadGaussConfig, X_HW_ID, X_HW_APPKEY, _STAR_RE, HW_USERINFO_API,
    CONV_ORDER, RESPONSE_BODY_MAX, PROMPT_PREFIX, MIN_CONVERSATION_LENGTH,
    DEFAULT_SCENE, AGENT_CENTER_URL, REQUEST_TIMEOUT, READ_DB_SCHEMA,
    STAGE2_WORKERS, TARGET_DEPART, DEPT_FAIL_AS_PROBLEM, MIN_PROMPT_COUNT,
    READ_WORKERS, CHUNK, UPSERT_BATCH, SESSION_MAX_ROWS, SESSION_MAX_BYTES
)
from db.sql_connector import get_sql_connector
from db_operate.sql_models import CodeAgentSessionSummary, CodeAgentDatalog, CodeAgentDatalogCli
from db_operate.sql_operator import SQLOperator
from models.llm_caller import LLMCaller

# 工号 -> (ok, depart) 缓存（只在主线程访问，无并发问题）
_dept_cache = {}
_dept_lock = threading.Lock()
_dept_session = requests.Session()  # 复用 TCP 连接，别每次新建


def _get_user_department(user_id: str) -> Tuple[bool, Optional[str]]:
    """根据工号查 hwDepartName3。

    返回 (ok, depart)：
        ok=False 表示请求或解析失败；
        ok=True 时 depart 为部门名（查无此人则为 None）。
    """
    if not user_id:
        return False, None

    with _dept_lock:
        cached = _dept_cache.get(user_id)
    if cached is not None:
        return cached

    try:
        resp = _dept_session.get(f"{HW_USERINFO_API}?info={user_id}",
                                 timeout=10, verify=False)
        resp.raise_for_status()
        data = resp.json()
        depart = (data[0] or {}).get("hwDepartName3") \
            if isinstance(data, list) and data else None
        result = (True, depart)
    except Exception as e:
        logger.warning("查询部门失败 user_id=%s: %s", user_id, e)
        result = (False, None)

    with _dept_lock:
        _dept_cache[user_id] = result
    return result  # 单个值


# ======================================================================
# 阶段一：清洗 / 合成 session summary（纯计算，不碰 DB）
# ======================================================================

def _looks_encrypted(text: str) -> bool:
    """对话历史里出现大段 * 说明内容被加密/打码"""
    return bool(_STAR_RE.search(text or ""))


def _extract_input_text(raw: str) -> Optional[str]:
    """从 first_input 的原始内容里只抽取 type=text 节点的 value.input 文本。

    first_input 可能是一个 JSON 数组字符串，元素形如：
        {"type": "text", "value": {"input": "..."}}   -> 取 input
        {"type": "file", "value": {...}}               -> 跳过
    多个 text 段按出现顺序拼接；解析失败或抽不到则原样返回。
    """
    if not raw:
        return raw
    try:
        data = json.loads(raw.strip())
    except (ValueError, TypeError):
        return raw  # 不是 JSON，原样返回，避免丢数据
    if not isinstance(data, list):
        return raw

    parts = []
    for item in data:
        if isinstance(item, dict) and item.get("type") == "text":
            val = item.get("value")
            if isinstance(val, dict):
                inp = val.get("input")
                if inp:
                    parts.append(str(inp))

    if not parts:
        return raw
    return "".join(parts).strip()


def _collect_scalars(rows: list) -> dict:
    """一次遍历抽出 session 级标量字段：
    user_id / 最早 trace 时间 / 是否用过 skill / ide 类型 / 代码仓 /
    最早的一条 prompt 及 prompt 总数。
    （同一行只有一个 attribute_key，故各分支用 elif 互斥即可。）
    """
    user_id = None
    first_trace_time = None
    used_skill = False
    ide_type = None
    remote_git_repo_path = None
    first_input = None
    first_input_key = None  # (time, pk)，用于挑选最早的一条 prompt
    prompt_count = 0

    for r in rows:
        if r is None:
            continue
        if user_id is None and getattr(r, "user_id", None):
            user_id = r.user_id

        sat = r.session_action_time
        if first_trace_time is None or (sat is not None and sat < first_trace_time):
            first_trace_time = sat

        key = r.attribute_key
        val = (r.attribute_value or "").strip()
        if key == "skill_name" and val:
            used_skill = True
        elif key == "ide_type" and ide_type is None and val:
            ide_type = r.attribute_value
        elif key == "remote_git_repo_path" and remote_git_repo_path is None and val:
            remote_git_repo_path = r.attribute_value
        elif key == "prompt" and val:
            prompt_count += 1
            k = (sat or "", r.pk_id or "")
            if first_input_key is None or k < first_input_key:
                first_input_key = k
                first_input = r.attribute_value

    return {
        "user_id": user_id,
        "first_trace_time": first_trace_time,
        "used_skill": used_skill,
        "ide_type": ide_type,
        "remote_git_repo_path": remote_git_repo_path,
        "first_input": first_input,
        "prompt_count": prompt_count,
    }


def _render_span(rows: list) -> str:
    """单个 span 内按规范顺序拼行；response_body 过长做截断。"""
    ordered = sorted(rows, key=lambda x: (CONV_ORDER[x.attribute_key], x.pk_id or ""))
    lines = []
    for x in ordered:
        val = x.attribute_value or ""
        if x.attribute_key == "response_body" and len(val) > RESPONSE_BODY_MAX:
            val = val[:RESPONSE_BODY_MAX] + "...（后续省略）"
        lines.append(f"[{x.attribute_key.upper()}] {val}")
    return "\n".join(lines)


def _build_conversation_history(rows: list) -> Optional[str]:
    """把 CONV_ORDER 内的行按 (trace_id, span_id) 分组，
    span 内按规范顺序拼，再把 span 按 (time, pk) 拼成全文。"""
    spans = OrderedDict()
    for r in rows:
        if r is None or r.attribute_key not in CONV_ORDER:
            continue
        k = (r.trace_id, r.span_id)
        sp = spans.get(k)
        if sp is None:
            sp = {"rows": [], "time": r.session_action_time, "pk": r.pk_id}
            spans[k] = sp
        sp["rows"].append(r)
        sat = r.session_action_time
        if sat is not None and (sp["time"] is None or sat < sp["time"]):
            sp["time"] = sat
        if r.pk_id is not None and (sp["pk"] is None or r.pk_id < sp["pk"]):
            sp["pk"] = r.pk_id

    blocks = [(sp["time"], sp["pk"], _render_span(sp["rows"])) for sp in spans.values()]
    blocks.sort(key=lambda b: (b[0] or "", b[1] or ""))
    return "\n\n".join(b[2] for b in blocks) if blocks else None


def build_session_summary(session_id: str, rows: list, session_date: str,
                          source: str = "gui") -> dict:
    """把一个 session 的所有行合成一条记录（纯计算，不碰 DB）。"""
    scalars = _collect_scalars(rows)
    conversation_history = _build_conversation_history(rows)

    # 问题判定：不以 [PROMPT] 开头，或对话历史被加密（大段 *）
    is_problem = (
            not (conversation_history or "").startswith("[PROMPT]")
            or _looks_encrypted(conversation_history)
    )

    return {
        "session_id": session_id,
        "user_id": scalars["user_id"],
        "first_trace_time": scalars["first_trace_time"],
        "conversation_history": conversation_history,
        # first_input 只保留 type=text 节点里的 input 文本
        "first_input": _extract_input_text(scalars["first_input"]),
        "ide_type": scalars["ide_type"],
        "remote_git_repo_path": scalars["remote_git_repo_path"],
        "used_skill": scalars["used_skill"],
        "is_problem": is_problem,
        "session_date": session_date,
        "source": source,
        "prompt_count": scalars["prompt_count"],
    }


def _log_session(s: dict):
    """逐 session 明细，改为 DEBUG 级别，默认不打印，避免刷屏。"""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    flag = "⚠ 问题" if s["is_problem"] else "正常"
    conv = s["conversation_history"] or ""
    preview = conv[:].replace("\n", " / ")
    logger.debug(
        "[%s] session=%s start=%s used_skill=%s conv_len=%d ide=%s repo=%s",
        flag, s["session_id"], s["first_trace_time"], s["used_skill"],
        len(conv), s["ide_type"], s["remote_git_repo_path"],
    )
    logger.debug("        预览: %s", preview)


# ======================================================================
# 阶段二：规则过滤 -> LLM 准入判定 -> 投递 Master Agent
# （原 skill_extractor.py 的内容，内联于此）
# ======================================================================

def rule_filter(conversation_history: str, prompt_count: Optional[int] = None) -> Optional[str]:
    text = (conversation_history or "").strip()

    if not text:
        return "empty: 对话历史为空"

    if not text.startswith(PROMPT_PREFIX):
        return "is_problem: 对话历史非 [PROMPT] 开头"

    if len(text) < MIN_CONVERSATION_LENGTH:
        return f"too_short: 长度 {len(text)} < {MIN_CONVERSATION_LENGTH}"

    # 新增：一句话需求不提 skill
    if prompt_count is not None and prompt_count < MIN_PROMPT_COUNT:
        return f"single_prompt: 仅 {prompt_count} 个 prompt，视为一句话需求"

    return None


def _parse_json_response(raw: str) -> dict:
    """从模型输出中稳健地解析 JSON；解析失败则保守判为不通过。

    兼容推理模型输出：<think>...</think> 前缀、只出现 </think> 闭合标签、
```json 围栏、思考文本中夹带 JSON 等情况。取最后一个能解析的 JSON 对象。"""
    text = (raw or "").strip()

    # 1. 剥掉思考段：优先按 </think> 截断（有些模型不输出 <think> 开头）
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[-1].strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # 2. 去掉代码围栏
    text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()

    # 3. 直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # 4. 兜底：非贪婪找出所有 {...} 候选，从最后一个往前试
    #    （最终答案一般在末尾；think 段里的半成品 JSON 排在前面）
    candidates = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, flags=re.DOTALL)
    for cand in reversed(candidates):
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict) and "task_completed" in obj:
                return obj
        except json.JSONDecodeError:
            continue

    return {
        "task_completed": False,
        "has_reusable_knowledge": False,
        "reason": f"无法解析模型输出: {(raw or '')[:500]}",
    }


def admission_judge(conversation_history, scene=DEFAULT_SCENE):
    prompt = ADMISSION_PROMPT_TEMPLATE.format(conversation_history=conversation_history)
    llm_caller = LLMCaller(scene=scene)

    raw = ""
    for attempt in range(3):
        raw = llm_caller.model_call(prompt) or ""
        if raw.strip():
            break
        time.sleep(5)

    if not raw.strip():
        # 上游真的没返回内容，标成可重试，而不是直接当 NO_SKILL
        return {"task_completed": False, "has_reusable_knowledge": False,
                "llm_failed": True, "reason": "LLM 返回空，建议重试"}

    return _parse_json_response(raw)


def _build_master_agent_message(conversation_history: str, employee_id: str, session_id: str) -> str:
    """构造发给 Master Agent 的消息，带上工号与 session_id。"""
    return (
        "请根据以下 Code Agent 对话历史归纳并生成一个可复用的 Skill"
        "要求满足『去实体化、适用广度、增量价值、可操作性』四个维度，"
        "合格后上传至扶摇 Skill 市场。\n"
        f"提交工号：{employee_id}\n"
        f"session_id：{session_id}（调用 skill upload 接口时请原样回传该 session_id）\n"
        "对话历史：\n"
        f"{conversation_history}"
    )


def send_to_agent_center(conversation_history: str, employee_id: str, session_id: str) -> dict:
    """把对话历史投递给 Agent Center 的 Master Agent。"""
    headers = {
        "X-HW-ID": X_HW_ID,
        "X-HW-APPKEY": X_HW_APPKEY,
        "Content-Type": "application/json",
    }
    payload = {
        "isStream": False,
        "source": "copy_api",
        "userId": employee_id,  # 工号
        "sessionId": session_id,  # 来源 session
        "isFormatSse": False,
        "message": _build_master_agent_message(conversation_history, employee_id, session_id),
        "hasSkill": True,
    }
    logger.debug("投递给 Master Agent 的消息：%s",
                 _build_master_agent_message(conversation_history, employee_id, session_id))

    resp = requests.post(
        AGENT_CENTER_URL,
        headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=REQUEST_TIMEOUT,
        verify=False
    )
    resp.raise_for_status()

    try:
        result = resp.json()
    except ValueError:
        result = {"raw_text": resp.text}

    logger.debug("Master Agent 返回：%s", result)
    return result


def run_stage2(conversation_history, employee_id, session_id,
               scene=DEFAULT_SCENE, prompt_count=None) -> dict:
    """
    阶段二主流程：规则过滤 -> 准入判定 -> 投递 Master Agent。

    返回:
        {"status": "NO_SKILL" | "SUBMITTED", "stage": ..., ...}
    """
    # 1. 规则过滤
    reason = rule_filter(conversation_history, prompt_count=prompt_count)
    if reason:
        return {"status": "NO_SKILL", "stage": "rule_filter", "reason": reason}

    # 2. LLM 准入判定（两条判据须全部满足）
    verdict = admission_judge(conversation_history, scene)
    if not (verdict.get("task_completed")
            and verdict.get("has_reusable_knowledge")
            and verdict.get("has_incremental_value")):
        return {
            "status": "NO_SKILL",
            "stage": "admission",
            "reason": verdict.get("reason"),
            "detail": verdict,
        }

    # 3. 投递给 Master Agent（生成 / 审查 / 上传在其内部完成）
    agent_response = send_to_agent_center(conversation_history, employee_id, session_id)
    return {
        "status": "SUBMITTED",
        "stage": "agent_center",
        "admission": verdict,
        "agent_response": agent_response,
    }


# ======================================================================
# 阶段二：在后台线程里投递（与阶段一并行）
# ======================================================================

_stats_lock = threading.Lock()
_stats = {"submitted": 0, "no_skill": 0, "errored": 0}


def _process_stage2(s: dict):
    """单条记录跑阶段二流水线。在线程池里执行，单条失败不影响整批。"""
    sid = s["session_id"]
    emp = s["user_id"]
    conv = s["conversation_history"]

    try:
        result = run_stage2(conv, employee_id=emp, session_id=sid,
                            prompt_count=s.get("prompt_count"))
    except Exception as e:
        with _stats_lock:
            _stats["errored"] += 1
        logger.error("session=%s 阶段二异常: %s", sid, e)
        return

    status = result.get("status")
    with _stats_lock:
        if status == "SUBMITTED":
            _stats["submitted"] += 1
        else:
            _stats["no_skill"] += 1

    logger.info("[%s] session=%s emp=%s stage=%s reason=%s",
                status, sid, emp, result.get("stage"), result.get("reason"))


# ======================================================================
# 编排：清洗一条，命中即投递；阶段二在后台并发跑
# ======================================================================
def _safe_rollback(op):
    """写库异常后 PostgreSQL 事务会进入 aborted 状态，后续写操作都会连环失败，
    必须回滚当前 session 才能继续。SQLOperator 内部结构未知，这里逐一探测常见位置，
    任何一步失败都安全忽略（若 SQLOperator 本身每次调用就 commit/rollback，这里就是无害的 no-op）。"""
    candidates = []
    for attr in ("session", "_session", "db_session"):
        sess = getattr(op, attr, None)
        if sess is not None:
            candidates.append(sess)
    conn = getattr(op, "connector", None)
    if conn is not None:
        for attr in ("session", "_session"):
            sess = getattr(conn, attr, None)
            if sess is not None:
                candidates.append(sess)
    for sess in candidates:
        try:
            sess.rollback()
            return True
        except Exception:
            logger.debug("通过 %r 回滚失败，尝试下一个", sess, exc_info=True)
    return False


@dataclass
class _PipelineCtx:
    """一次运行内共享的资源，避免逐层函数传一长串参数。"""
    read_op: SQLOperator
    write_op: SQLOperator
    read_pool: ThreadPoolExecutor
    stage2_pool: ThreadPoolExecutor


def _fetch_session_sizes(read_op, sids: list, model) -> dict:
    """分批查各 session 的行数 / 字节数。"""
    sizes = {}
    for i in range(0, len(sids), 500):
        sizes.update(read_op.get_session_sizes(sids[i:i + 500], model=model))
    return sizes


def _filter_oversized(sids: list, sizes: dict, source: str) -> list:
    """剔除行数或字节数超限的 session，返回保留下来的 sids。"""
    oversized = {
        sid
        for sid in sids
        if sizes.get(sid, (0, 0))[0] > SESSION_MAX_ROWS
           or sizes.get(sid, (0, 0))[1] > SESSION_MAX_BYTES
    }
    if not oversized:
        return sids
    for sid in oversized:
        cnt, total_bytes = sizes[sid]
        logger.warning("跳过超大 session=%s：%d 行 / %.1f MB",
                       sid, cnt, total_bytes / 1048576)
    kept = [s for s in sids if s not in oversized]
    logger.info("[%s] 过滤超大 session %d 个，剩余 %d 个",
                source, len(oversized), len(kept))
    return kept


def _safe_fetch(read_op, chunk: list, model) -> dict:
    """单个 chunk 拉取失败只丢这一批，不让整个 pipeline 中断。"""
    try:
        return read_op.get_session_rows_bulk(chunk, model=model)
    except BaseException as e:  # MemoryError 不是 Exception 子类，也要接住
        logger.error("chunk(%d 个 session) 拉取失败，跳过：%s", len(chunk), e)
        logger.debug(traceback.format_exc())
        return {}


def _prewarm_departments(rows_map: dict):
    """本批工号并发预热部门缓存，主循环只读缓存。"""
    uids = {r[0].user_id for r in rows_map.values() if r and r[0].user_id}
    todo = [u for u in uids if u not in _dept_cache]
    if todo:
        with ThreadPoolExecutor(max_workers=16) as p:
            list(p.map(_get_user_department, todo))


def _apply_department_rule(s: dict):
    """按部门归属就地修正 is_problem（缓存命中，不再发请求）。"""
    ok, depart = _get_user_department(s["user_id"])
    if ok:
        if depart != TARGET_DEPART:
            s["is_problem"] = True
    elif DEPT_FAIL_AS_PROBLEM:
        s["is_problem"] = True


def _flush_buffer(buf: list, ctx: _PipelineCtx, st: dict):
    """把缓冲区落库并清空、累加写入计数。"""
    if not buf:
        return
    ctx.write_op.bulk_upsert_session_summary(buf)
    st["written"] += len(buf)
    buf.clear()


def _handle_session(sid, rows, day, source, st, buf, ctx: _PipelineCtx):
    """清洗单个 session -> 部门规则 -> 入库 -> 按需投递阶段二。
    单条失败只记数不影响整批。"""
    try:
        s = build_session_summary(sid, rows, day, source=source)
    except Exception as e:
        st["errored"] += 1
        logger.error("[%s] session=%s 清洗失败：%s", source, sid, e)
        logger.debug(traceback.format_exc())
        return

    st["total"] += 1
    if not s["user_id"]:
        st["no_user"] += 1
        return

    _apply_department_rule(s)

    # 入库副本不存对话全文，省空间；阶段二仍用内存里的全量
    db_row = dict(s)
    db_row["conversation_history"] = ""
    buf.append(db_row)
    if len(buf) >= UPSERT_BATCH:
        _flush_buffer(buf, ctx, st)

    _log_session(s)
    st["problem"] += int(s["is_problem"])
    st["skilled"] += int(s["used_skill"])

    if (not s["used_skill"]) and (not s["is_problem"]):
        st["candidates"] += 1
        ctx.stage2_pool.submit(_process_stage2, dict(s))  # 用原始 s（含全文）


def _process_source(source, model, day, ctx: _PipelineCtx):
    """处理单一来源（gui / cli）的全部 session。"""
    sids = [s for s in ctx.read_op.get_day_session_ids(day, model=model) if s]
    logger.info("==== %s [%s]: 当天出现过 %d 个 session ====", day, source, len(sids))

    sizes = _fetch_session_sizes(ctx.read_op, sids, model)
    sids = _filter_oversized(sids, sizes, source)

    st = {"total": 0, "problem": 0, "skilled": 0,
          "candidates": 0, "no_user": 0, "written": 0, "errored": 0}
    buf = []
    chunks = [sids[i:i + CHUNK] for i in range(0, len(sids), CHUNK)]

    # read_pool.map 惰性产出：拉完一个 chunk 就立刻处理，边拉边算边投
    for rows_map in ctx.read_pool.map(lambda c: _safe_fetch(ctx.read_op, c, model), chunks):
        _prewarm_departments(rows_map)
        for sid, rows in rows_map.items():
            _handle_session(sid, rows, day, source, st, buf, ctx)

    _flush_buffer(buf, ctx, st)

    logger.info(
        "==== [%s] 阶段一完成：扫描 %d，清洗 %d，缺工号 %d，写入 %d，异常 %d；"
        "用过 skill %d，问题 %d，阶段二候选 %d ====",
        source, len(sids), st["total"], st["no_user"], st["written"], st["errored"],
        st["skilled"], st["problem"], st["candidates"],
    )


def run_pipeline_once(day: str):
    sources = [("gui", CodeAgentDatalog), ("cli", CodeAgentDatalogCli)]
    read_op = SQLOperator(connector=get_sql_connector(
        config=ReadGaussConfig, schema=READ_DB_SCHEMA))
    write_op = SQLOperator()

    CodeAgentSessionSummary.__table__.create(
        bind=get_sql_connector().engine, checkfirst=True)

    stage2_pool = ThreadPoolExecutor(max_workers=STAGE2_WORKERS)
    read_pool = ThreadPoolExecutor(max_workers=READ_WORKERS)
    ctx = _PipelineCtx(read_op, write_op, read_pool, stage2_pool)
    try:
        for source, model in sources:
            _process_source(source, model, day, ctx)
    finally:
        read_pool.shutdown(wait=True)
        logger.info("==== 阶段一完毕，等待阶段二收尾 ====")
        stage2_pool.shutdown(wait=True)

    logger.info("==== 阶段二完成：投递 %d，无 skill %d，异常 %d ====",
                _stats["submitted"], _stats["no_skill"], _stats["errored"])


def _target_day() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    return (datetime.now().date() - timedelta(days=3)).isoformat()


if __name__ == "__main__":
    run_pipeline_once(_target_day())
