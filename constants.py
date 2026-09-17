# constants.py
from dataclasses import dataclass
from enum import Enum
from typing import Final

# Elasticsearch 字段常量
SESSION_ID: Final[str] = "session_id"
USER_ID: Final[str] = "user_id"
SCENE: Final[str] = "scene"
CREATE_TIME: Final[str] = "create_time"
SYSTEM_PROMPT: Final[str] = "system_prompt"
ROLE: Final[str] = "role"
DELEGATE_SESSION_ID: Final[str] = "delegate_session_id"
DELEGATE_ACTION: Final[str] = "delegate_action"
CONTEXT: Final[str] = "context"
KEYWORDS: Final[str] = "keywords"
TAGS: Final[str] = "tags"
CREATE_DATE: Final[str] = "create_date"
LAYER_CATEGORY: Final[str] = "layer_category"
NAME: Final[str] = "name"
FUNCTION = "function"
FUNCTION_CALL: Final[str] = "function_call"
ARGUMENTS: Final[str] = "arguments"
SESSION: Final[str] = "Session"
LONGTERM: Final[str] = "LongTerm"
IS_DELETE: Final[str] = "is_delete"
CONTENT_HASH_CODE: Final[str] = "content_hash_code"

# Elasticsearch 查询常量
BOOL: Final[str] = "bool"
MUST: Final[str] = "must"
MUST_NOT: Final[str] = "must_not"
TERM: Final[str] = "term"
RANGE: Final[str] = "range"
GTE: Final[str] = "gte"
LTE: Final[str] = "lte"
QUERY: Final[str] = "query"
CONTENT: Final[str] = "content"
INDEX: Final[str] = "index"
SORT: Final[str] = "sort"
SOURCE: Final[str] = "_source"
SIZE: Final[str] = "size"
ORDER: Final[str] = "order"
DESC: Final[str] = "desc"
ASC: Final[str] = "asc"
HITS: Final[str] = "hits"
AGGREGATIONS: Final[str] = "aggregations"
MAX_CREATE_TIME: Final[str] = "max_create_time"
VALUE: Final[str] = "value"

# 环境信息标签常量
ENVIRONMENT_INFO_TAG: Final[str] = "<environment_info>"

# Redis任务管理
TASK_ID: Final[str] = "task_id"
TASK_STATUS: Final[str] = "task_status"
TASK_DATA: Final[str] = "task_data"

# 委派相关字段
DELEGATE_INFO: Final[str] = "delegate_info"

WORK_PROCESS: Final[str] = "work_process"
LONG_TERM_MEMORY: Final[str] = "long_term_memory"

EPS = 1e-10


class RoleType:
    USER = "user"
    ASSISTANT = "assistant"
    FUNCTION = "function"
    DELEGATE = "delegate"


# 压缩相关
class ContentType:
    """内容类型枚举"""
    MARKDOWN = "markdown"
    JSON = "json"
    CODE = "code"
    TEXT = "text"


UNKNOWN = "unknown"

# 压缩切片相关
CHUNK_ID = "chunk_id"
PREVIOUS_CHUNK_ID = "previous_chunk_id"
NEXT_CHUNK_ID = "next_chunk_id"
START_LINE = "start_line"
END_LINE = "end_line"

# 向量维度
DIM_384: Final[int] = 384

# 处理过程压缩
AGENT_ID = "agent_id"
PROCESS_AGENT = "b4536da7-bc37-4e6d-ab6c-ac0ea4076c38"
PROCESS_TEST_AGENT = "8720b93f-f556-4328-a0d8-f7ac7e8a89a9"
COMPRESSION_PROCESSOR = "compression_processor"

# 云核通用编码agent意图识别对应表
CODING_AGENT_MAP = {
    "2": "6588cdcd-da73-438c-a092-a2548b813cb9",
    "1": "9c071e52-5917-4627-bb37-4cf9d391d70c",
    "3": "52865f78-0d70-4268-a4ed-d502006e6654"
}

# 云核通用编码agent主agent
CODING_AGENT_ID = "48e7450c-0ef6-4ad2-a2ce-653b2e81045a"
CODING_AGENT_TEST_ID = "54e6c3ce-3069-42cb-b259-8e61fab9f9db"

# 定时任务相关
MEMORY_AND_PROCESS_EXTRACT = "MEMORY_AND_PROCESS_EXTRACT"
MEMORY_CLEAN = "MEMORY_CLEAN"
INTERVAL = "interval"
INTERVAL_DAYS = "interval_days"
INTERVAL_HOURS = "interval_hours"
INTERVAL_MINUTES = "interval_minutes"
RUN_IMMEDIATELY = "run_immediately"
ENABLED = "enabled"


class CompressionStatus(str, Enum):
    """压缩状态枚举"""
    PENDING = "pending"  # 压缩中
    SUCCESS = "success"  # 成功，待应用
    APPLIED = "applied"  # 已应用
    FAILED = "failed"  # 失败


@dataclass
class CompressionConfig:
    """压缩配置"""
    token_limit: int = 90000
    trigger_threshold: float = 0.5
    keep_ratio: float = 0.3
    token_budget: int = 4000
    pending_timeout_minutes: int = 5  # pending 超时时间（分钟）


DELEGATE = "delegate"
NA: Final[str] = "N/A"
ID: Final[str] = "id"
COMPRESSION_TIME: Final[str] = "compression_time"
ORIGINAL_TOKEN_COUNT: Final[str] = "original_token_count"
COMPRESSED_TOKEN_COUNT: Final[str] = "compressed_token_count"
COMPRESSION_RATIO: Final[str] = "compression_ratio"
MESSAGES_COMPRESSED_COUNT: Final[str] = "messages_compressed_count"
MESSAGES_KEPT_COUNT: Final[str] = "messages_kept_count"
KEPT_MESSAGES_START_INDEX: Final[str] = "kept_messages_start_index"
COMPRESSED_SUMMARY: Final[str] = "compressed_summary"
STATUS: Final[str] = "status"
ERROR_MESSAGE: Final[str] = "error_message"
ORIGINAL_TOKENS: Final[str] = "original_tokens"
COMPRESSED_TOKENS: Final[str] = "compressed_tokens"
USER: Final[str] = "user"
KEPT_USER_COUNT: Final[str] = "kept_user_count"
KEPT_ASSISTANT_COUNT: Final[str] = "kept_assistant_count"
COMPRESSED_ASSISTANT_COUNT: Final[str] = "compressed_assistant_count"
COMPRESSED_INDICES: Final[str] = "compressed_indices"
COMPRESSED_CREATE_TIMES: Final[str] = "compressed_create_times"
ASSISTANT = "assistant"

_SORT_INDEX: Final[str] = "_sort_index"
IS_COMPRESSION_SUMMARY: Final[str] = "is_compression_summary"
MEMORY: Final[str] = "memory"
DELEGATE_OBSERVATION: Final[str] = "delegate_observation"
MODEL_ID: Final[str] = "model_id"
IS_CANCEL: Final[str] = "is_cancel"
ERROR_CODE: Final[str] = "error_code"
COMPRESSION = "compression"
COMPRESSION_APPLIED: Final[str] = "compression_applied"
ORIGINAL_MESSAGE_COUNT: Final[str] = "original_message_count"
REBUILT_MESSAGE_COUNT: Final[str] = "rebuilt_message_count"
COMPRESSED_INDEX_RANGE: Final[str] = "compressed_index_range"

KEPT_START_INDEX: Final[str] = "kept_start_index"

# 解密相关环境变量常量
ROOTKEY_TWO: Final[str] = "ROOTKEY_TWO"
ROOTKEY_THREE: Final[str] = "ROOTKEY_THREE"
ROOTKEY_IV: Final[str] = "ROOTKEY_IV"
WORKKEY_KEY: Final[str] = "WORKKEY_KEY"
WORKKEY_IV: Final[str] = "WORKKEY_IV"
PBKDF2_SALT: Final[str] = "PBKDF2_SALT"

# 解密所需环境变量列表
DECRYPT_SECRET_KEYS: Final[list[str]] = [
    ROOTKEY_TWO,
    ROOTKEY_THREE,
    ROOTKEY_IV,
    WORKKEY_KEY,
    WORKKEY_IV,
    PBKDF2_SALT,
]

# 数据库类型常量
DB_TYPE_MYSQL = "mysql"
DB_TYPE_GAUSSDB = "gaussdb"

PARENT_SCENE = "parent_scene"
TITLE = "title"
SUMMARY = "summary"
VECTORS = "vectors"
EXPERIENCE = "experience"
PRODUCT = "product"
METADATA = "metadata"
DOC_ID = "doc_id"
CREATED_AT = "created_at"
UPDATED_AT = "updated_at"
CODE = "code"
LOG = "log"
PROMPT = "prompt"
BATCH_INPUT = "batch_input"
DATA = "data"
TITLE_VECTOR = "title_vector"
SEARCH_TEXTS = "search_texts"
FILTER = "filter"
USERID = "userid"
SCORE = "score"
SCORE_FINAL = "final_score"
SCORE_VECTOR_RAW = "vector_raw"
SCORE_VECTOR_NORM = "vector_norm"
SCORE_BM25_RAW = "bm25_raw"
SCORE_BM25_NORM = "bm25_norm"
TOTAL = "total"
SCENE_ID = "scene_id"
SUMMARY_VECTOR = "summary_vector"
EXPERIENCE_VECTOR = "experience_vector"
RAG_SEARCH_TEXT = "rag_search_text"
RAG_SEARCH_TEXT_VECTOR = "rag_search_text_vector"

# 变更类型
ACTION_OVERWRITTEN = "overwritten"  # create 时 doc_id 已存在 → 覆盖旧版
ACTION_DELETED = "deleted"
ACTION_ROLLBACK = "rollback"

# ---- 接口路径（用于把一条请求归类为 生成 / 检索）----
EXPERIENCE_PREFIX = "/memory/experience"
_URL_CREATE = f"{EXPERIENCE_PREFIX}/doc"
_URL_SEARCH = f"{EXPERIENCE_PREFIX}/doc/search"
_URL_SEARCH_BY_FILTER = f"{EXPERIENCE_PREFIX}/doc/search/by-filter"

CATEGORY_SEARCH = "search"  # 混合检索 /doc/search
CATEGORY_SEARCH_BY_FILTER = "search_by_filter"  # 条件检索 /doc/search/by-filter

CALLER_ID_KEY = "caller_id"

# 生成统计里"上传者"用哪个 ES 字段（当前用 user_id）
GENERATION_UPLOADER_FIELD = USER_ID

CODE_AGENT_PIPELINE = 'CODE_AGENT_PIPELINE'
RUN_AT_HOUR = 'run_at_hour'
RUN_AT_MINUTE = 'run_at_minute'
