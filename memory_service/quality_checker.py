import json
import re
from typing import Optional

from pydantic import BaseModel

from logger import logger
from models.llm_caller import LLMCaller
from project_configs.prompt_configs import QUALITY_CHECK_PROMPT
from project_configs.settings import UNIFIED_INDEX


class QualityResult(BaseModel):
    passed: bool
    reason: Optional[str] = None
    category: Optional[str] = None  # "over_obvious" | "too_specific" | "low_applicability"


def check_experience_quality(content: str) -> QualityResult:
    """同步调用大模型评估经验质量"""
    prompt = QUALITY_CHECK_PROMPT.format(content=content)
    llm_caller = LLMCaller(scene="compress")
    llm_response = llm_caller.model_call(prompt)
    logger.info(f"Quality check response: {llm_response}")
    pattern = r"(?:```json\s*)?(\{.*?\})(?:\s*```)?"
    match = re.search(pattern, llm_response, re.S)

    if match:
        json_str = match.group(1)
    else:
        raise ValueError("No JSON object found in the response")
    parsed = json.loads(json_str)
    return QualityResult(**parsed)


def build_quality_field(result: QualityResult) -> dict:
    """构建写入 ES 的 quality 相关字段"""
    return {
        "quality": result.passed,
        "quality_category": result.category,
        "quality_reason": result.reason,
    }


def run_quality_check_and_update(doc_id: str, content: str) -> None:
    """后台任务：执行质量检查 → 回填 ES 文档的 quality 字段。
    由 FastAPI BackgroundTasks 调用，不阻塞主请求。
    """
    from memory_service.experience_manage import get_es_client

    try:
        quality_result = check_experience_quality(content)
        update_fields = build_quality_field(quality_result)
    except Exception as e:
        logger.warning(f"质量检查失败 doc_id={doc_id}: {e}")
        update_fields = {
            "quality": None,
            "quality_category": None,
            "quality_reason": f"quality check failed: {str(e)}",
        }

    try:
        es = get_es_client()
        es.update(index=UNIFIED_INDEX, id=doc_id, body={"doc": update_fields})
        logger.info(f"质量检查完成 doc_id={doc_id}, passed={update_fields.get('quality')}")
    except Exception as e:
        logger.error(f"质量检查回填失败 doc_id={doc_id}: {e}")
