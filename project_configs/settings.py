import os
import re

from typing import Set
from zoneinfo import ZoneInfo

from constants import TITLE_VECTOR, SUMMARY_VECTOR, EXPERIENCE_VECTOR, RAG_SEARCH_TEXT_VECTOR, SCENE, \
    USER_ID, METADATA, LOG, PRODUCT, SEARCH_TEXTS, VECTORS, SCENE_ID, TITLE, SUMMARY, EXPERIENCE, RAG_SEARCH_TEXT

# 先兜底,避免循环依赖时 settings 还没初始化完
APP_ENV = os.path.basename(os.getenv("PUBLISH_TYPE", "").lower())
NAMO_ENV_LIST = ["namo-beta", "namo-prod"]
NAMO_PROD = "namo-prod"
namo_settings = None


class ServerConfig:
    APP_ID = 'com.huawei.ipd.coretool.coremlops'
    DEFAULT_HOST_IP = "0.0.0.0"
    DEFAULT_PORT = 8080
    SUCCESS_CODE = 200


class LogConfig:
    LOG_FILE = 'memory_log'
    SUFFIX = "_%Y-%m-%d.log"  # 日志后缀
    WHEN = 'midnight'  # 每夜0点切割
    BACKUP_COUNT = 7  # 保留7天日志


class HeaderConfig:
    X_HW_ID = "com.huawei.ipd.coretool.coremlops"
    X_HW_APPKEY = "20240712174036MruoYvmsvKylrNXSND2SCrP8HKR9u3K5a6yZuZJZTK8=1X@2X/qBMrUV6rirzIXswNLig=="


class LLMConfig:
    MODEL_GATE_URL = "https://apigw-05.huawei.com/stream/public/model/run"


class CompressConfig:
    TOKEN_THRESHOLD = 8192
    COMPRESS_LLM_TOKEN_LIMIT = 4096
    COMPRESS_URL_encry = "20240712174036NNnZc9FOIDQJzWrgtodZFHWP17i86QU/bnkQAuwA2EtUBAsOPhdM8EyRkC8ePQot1X@ecPo8Yn" \
                         "ENfyp8KO8ILflxQ=="


class ProdEsConfig:
    HOST = "20240712174036pQDNbjbYO7s1xyMhp9hP0g==1X@fzBdAr2IhD+kNr61dmqjsg=="
    PORT = "30711"
    USERNAME = "20240712174036dOmLk1HxrJ7TwEUXB94rsg==1X@lzdzJ8ClajqzkbYEbd+21A=="
    PASSWORD = "20240712174036dOmLk1HxrJ7TwEUXB94rsg==1X@lzdzJ8ClajqzkbYEbd+21A=="
    HISTORY_INDEX = "session_history"
    SYSTEM_PROMPT_INDEX = "session_sys_prompt"
    LONGTERM_MEMORY_INDEX = "long_term_memorys"
    DEFAULT_Config = {"size": 1000}


class TestEsConfig:
    HOST = "20240712174036K6vDpQhJBjvfP4Xyj8E+fA==1X@jcmIt8eEcJpWc/yPZrHrVg=="
    PORT = "30701"
    USERNAME = "20240712174036dOmLk1HxrJ7TwEUXB94rsg==1X@lzdzJ8ClajqzkbYEbd+21A=="
    PASSWORD = "20240712174036dOmLk1HxrJ7TwEUXB94rsg==1X@lzdzJ8ClajqzkbYEbd+21A=="
    HISTORY_INDEX = "session_history"
    SYSTEM_PROMPT_INDEX = "session_sys_prompt"
    LONGTERM_MEMORY_INDEX = "long_term_memorys"
    DEFAULT_Config = {"size": 1000}


class ProdRedisConfig:
    HOST = "20240712174036cG7f4+oCZyXY9DEtPOlGMw==1X@Qjdg1uUFFIEEcjn7TZePzA=="
    PORT = 32429
    DB = 0
    TASK_QUEUE_KEY = "queue:tasks"
    CURRENT_SESSIONS_KEY = "set:currently_processing"

    PROCESS_EXTRACT_TASK_QUEUE_KEY = "queue:process_extract_tasks"
    PROCESS_EXTRACT_CURRENT_SESSIONS_KEY = "set:process_extract_currently_processing"


class TestRedisConfig:
    HOST = "20240712174036cG7f4+oCZyXY9DEtPOlGMw==1X@Qjdg1uUFFIEEcjn7TZePzA=="
    PORT = 32429
    DB = 1
    TASK_QUEUE_KEY = "queue:tasks"
    CURRENT_SESSIONS_KEY = "set:currently_processing"

    PROCESS_EXTRACT_TASK_QUEUE_KEY = "queue:process_extract_tasks"
    PROCESS_EXTRACT_CURRENT_SESSIONS_KEY = "set:process_extract_currently_processing"


class TaskFilterConfig:
    MEMORY_EXTRACT_TASK_KEY = "代码生成"
    PROCESS_EXTRACT_TASK_KEY = "代码生成"


class EmbedConfig:
    DEFAULT_MODEL = "paraphrase"


# 测试数据库连接信息
class TestModelAnalyiseSQLConfig:
    host = "gauss.mlops-test.rnd.huawei.com"
    port = 8000
    dbname = "mlops"
    user = "202407121740364zAmPrwMnE9P3GUffBp3rA==1X@dkP5FAxicSpNsPnZ0gTCwQ=="
    passwd = "20240712174036AjMdJw8EIm5ESAZi21GxvA==1X@aI251xHfGuYjiexZQgJy0Q=="


# 生产数据库连接信息
class ProdModelAnalyiseSQLConfig:
    host = "gauss.mlops.rnd.huawei.com"
    port = 8000
    dbname = "mlops"
    user = "20240712174036F4ngGmkf8c3NTmUewln/Yg==1X@DZGlnCRWB6JWCBHUB53dUw=="
    passwd = "20240712174036FUekIE28km3+FxE1qcvl8w==1X@kl9yMbnwBCH+W7LiBWF3OQ=="


class TestUrlConfig:
    memory_url_prefix = "https://coremlops-beta.rnd.huawei.com/memory"
    agent_info_url_prefix = "202407121740364KnjHlT9cQ0AKC0s4Y/fK/9aRPTEei3EjJ/4dffZI" \
                            "2IqAu0JiRi7SNdkiA9Wk4YXX14S0KdehqBPOVHGRp19Tg==1X@ffk2nK+CtNEsXNSo2ZLL1Q=="


class ProdUrlConfig:
    memory_url_prefix = "https://fuyao.rnd.huawei.com/memory"
    agent_info_url_prefix = "20240712174036vXDC4YgeFQaFX9OXmsJIsaLnX4WjD4SM5JVAtlYmJT" \
                            "ySDhX35c+/AJamgy9M4dsqMsiekYdQd8Iio1iT/UYv1w==1X@9YUQF6LrITLNIOWdhl2K4Q=="


# 添加环境参数
class EnvArgs:
    env = os.getenv("env", "test")


# 到这里 ServerConfig / LogConfig 已经存在了，再去加载 env_config 就不会循环依赖
try:
    from project_configs import env_config as _env

    APP_ENV = _env.APP_ENV
    NAMO_ENV_LIST = _env.NAMO_ENV_LIST
    namo_settings = _env.namo_settings
except Exception:
    # env_config 加载失败时，继续使用兜底值
    pass

# namo配置分支
# 1. 动态创建namo配置类（仅在namo环境生效）
if APP_ENV in NAMO_ENV_LIST and namo_settings:
    # 动态生成MySQL配置类（复用原有结构）
    class NamoModelAnalyiseSQLConfig:
        host = namo_settings.DB_HOST
        port = namo_settings.DB_PORT
        dbname = namo_settings.DB_NAME
        user = namo_settings.DB_USER  # 已解密的账号
        passwd = namo_settings.DB_PASSWORD  # 已解密的密码


    # 动态生成ES配置类
    class NamoEsConfig:
        HOST = namo_settings.ES_HOST
        PORT = namo_settings.ES_PORT
        USERNAME = ""  # namo ES无账号
        PASSWORD = ""  # namo ES无密码
        HISTORY_INDEX = namo_settings.ES_INDEX
        SYSTEM_PROMPT_INDEX = "session_sys_prompt"
        LONGTERM_MEMORY_INDEX = "long_term_memorys"
        DEFAULT_Config = {"size": 1000}


    # namo Redis配置类
    class NamoRedisConfig:
        HOST = namo_settings.REDIS_HOST
        PORT = namo_settings.REDIS_PORT
        DB = 0  # 沿用原有默认值
        TASK_QUEUE_KEY = "queue:tasks"
        CURRENT_SESSIONS_KEY = "set:currently_processing"
        PROCESS_EXTRACT_TASK_QUEUE_KEY = "queue:process_extract_tasks"
        PROCESS_EXTRACT_CURRENT_SESSIONS_KEY = "set:process_extract_currently_processing"


    # 加载namo配置
    ModelAnalyiseSQLConfig = NamoModelAnalyiseSQLConfig
    EsConfig = NamoEsConfig
    RedisConfig = NamoRedisConfig
    UrlConfig = ProdUrlConfig if APP_ENV == NAMO_PROD else TestUrlConfig
    UNIFIED_INDEX = ""  # 经验索引，namo环境不需要
    INDEX_NAME = ""
else:
    # 非namo环境：沿用原有逻辑
    ModelAnalyiseSQLConfig = TestModelAnalyiseSQLConfig if EnvArgs.env == "test" else ProdModelAnalyiseSQLConfig
    EsConfig = TestEsConfig if EnvArgs.env == "test" else ProdEsConfig
    RedisConfig = TestRedisConfig if EnvArgs.env == "test" else ProdRedisConfig
    UrlConfig = TestUrlConfig if EnvArgs.env == "test" else ProdUrlConfig
    UNIFIED_INDEX = "unified_experience_index_v4" if EnvArgs.env == "test" else "prod_unified_experience_index_v4"
    INDEX_NAME = "test_case_steps5-test" if EnvArgs.env == "test" else "test_case_steps5"

TASK_RUNNER_CONFIG = {
    'MEMORY_AND_PROCESS_EXTRACT': {
        'enabled': False,
        'interval_days': 7, 'interval_hours': 0, 'interval_minutes': 0
    },
    'MEMORY_CLEAN': {
        'enabled': True,
        'interval_days': 7, 'interval_hours': 0, 'interval_minutes': 0
    },
    'CODE_AGENT_PIPELINE': {
        'enabled': True,
        'run_at_hour': 21,  # 凌晨 1 点
        'run_at_minute': 0,
    },
}


def load_agent_set_from_env(env_key: str) -> Set[str]:
    """
    从环境变量中读取 agent id 列表，逗号分隔
    """
    raw = os.getenv(env_key, "")
    return {
        item.strip()
        for item in raw.split(",")
        if item.strip()
    }


# 从环境变量加载
COMPRESSION_ALLOWED_AGENTS = load_agent_set_from_env(
    "COMPRESSION_ALLOWED_AGENTS"
)

WHITELIST_REQUIRED_AGENTS = load_agent_set_from_env(
    "WHITELIST_REQUIRED_AGENTS"
)

EMBEDDING_MODELS = {
    "paraphrase": {
        "url": "http://service.coreai.rnd.huawei.com/prod/v-eukkjguxxvayecz6/stream",
        "dims": 384,
    },
    "m3e": {
        "url": "http://service.coreai.rnd.huawei.com/prod/v-y3epb9a9fqco9db6/stream",
        "dims": 768,
    },
    "codebert": {
        "url": "http://service.coreai.rnd.huawei.com/prod/v-jyxyksyrbbflgsnj/stream",
        "dims": 768,
    },
    "codet5p": {
        "url": "http://service.coreai.rnd.huawei.com/prod/v-fjfw4sczgrv6esbv/stream",
        "dims": 256,
    },
    "qwen3": {
        "url": "http://service.coreai.rnd.huawei.com/prod/v-morbxgeejbfaqhqa/stream",
        "dims": 1024,
    },
    "bge-code-v1": {
        "url": "http://service.coreai.rnd.huawei.com/prod/v-fhxfnsjpwh6zqbqf/stream",
        "dims": 1536,
    },
}

ES_HOSTS = [{"host": "7.221.172.172", "port": "9200"}]
ES_USERNAME = "cssuser"
ES_PASSWORD = "20240712174036N6GtFNNsdB+Y7tlM6Y4eKQ==1X@3OHKnbbFucVFeP8yCPHJyA=="

# Embedding 模型配置
DEFAULT_EMBEDDING_MODEL = "paraphrase"

BM25_CANDIDATE_MULTIPLIER = 5

# 检索字段 → 向量字段 的映射关系
SEARCH_FIELD_CONFIG = {
    "step_description": "step_vector",
    "checkpoint": "checkpoint_vector",
    "detailed_step_description": "detailed_step_description_vector",
}

# 返回结果时排除的字段
EXCLUDE_FIELDS = ["step_vector", "checkpoint_vector", "detailed_step_description_vector", ]

# 向量化字段与对应的 vector 存储字段的映射
VECTOR_FIELD_MAP = {
    "title": TITLE_VECTOR,
    "summary": SUMMARY_VECTOR,
    "experience": EXPERIENCE_VECTOR,
    "rag_search_text": RAG_SEARCH_TEXT_VECTOR,
}

# BM25 可检索字段映射（文本字段名 -> ES 中的字段路径）
BM25_FIELD_MAP = {
    "title": "title",
    "summary": "summary",
    "experience": "experience",
    "rag_search_text": "rag_search_text",
}

MAX_HIT_CAP = 1000

SIMPLE_FILTER_FIELDS = {
    "scene": SCENE,
    "scene_id": SCENE_ID,
    "user_id": USER_ID,
}

EXCLUDED_SOURCE_FIELDS = frozenset({
    SEARCH_TEXTS, VECTORS, TITLE_VECTOR, SUMMARY_VECTOR,
    EXPERIENCE_VECTOR, RAG_SEARCH_TEXT_VECTOR,
})

# 可选文本字段 -> (文本字段常量, 向量字段常量, 向量化后的字段名)
OPTIONAL_VECTOR_FIELDS = [
    ("experience", EXPERIENCE_VECTOR, "experience_vector"),
    ("rag_search_text", RAG_SEARCH_TEXT_VECTOR, "rag_search_text_vector"),
]

# 直接赋值的非文本字段: (body 属性名, ES 字段常量, 转换函数 or None)
UPDATE_PLAIN_FIELDS = [
    ("scene", SCENE, None),
    ("user_id", USER_ID, None),
    ("metadata", METADATA, None),
    ("log", LOG, None),
    ("product", PRODUCT, lambda v: v.dict(exclude_none=True)),
]

# (body 属性名, ES 字段常量, 向量字段常量 or None)
UPDATE_TEXT_FIELDS = [
    ("title", TITLE, TITLE_VECTOR),
    ("summary", SUMMARY, SUMMARY_VECTOR),
    ("experience", EXPERIENCE, EXPERIENCE_VECTOR),
    ("rag_search_text", RAG_SEARCH_TEXT, RAG_SEARCH_TEXT_VECTOR),
]

CST = ZoneInfo("Asia/Shanghai")

GET_PDUNAME_URL = "https://corealm-green.rnd.huawei.com/core_config/v1/rest/hw_userinfo/detail?info="

CALLER_ID_REQUIRED = False


class ReadGaussConfig:
    host = "dws-pro-dm-cloud-core-ioc-dws.hic.cloud"
    port = "8000"
    dbname = "cloud_core_ioc"
    user = "20240712174036m8vuQs/3kDLZNQiyNjf5YQ==1X@7EmvU26zCtaj8E1UJ6ZUkw=="
    passwd = "20240712174036TlujUPaxIuJdyMid7e4qWQ==1X@wGKJVsj4iZuXCWioCQ8MkQ=="


X_HW_ID = "com.huawei.ipd.coretool.coremlops"
X_HW_APPKEY = "3JUnVhZLKMnlO3FPOAwOxA=="

SKILL_DRAFTS_URL = "https://aicommunity.coreai.rnd.huawei.com/aiapp-v2/api/skill-drafts"

# 读取来源数据的新 Gauss 库
READ_DB_SCHEMA = "udata_dwr"

# 阶段二并发度：Agent Center 慢，开几个线程并行投递；按对端承受能力调
STAGE2_WORKERS = 3

# 工号 -> 部门 查询接口
HW_USERINFO_API = "https://corealm-green.rnd.huawei.com/core_config/v1/rest/hw_userinfo/detail"
# 只有这个产品线不算问题，其它一律标记为问题
TARGET_DEPART = "云核心网产品线"
# 查询部门失败（网络异常/查无此人）时是否标记为问题
DEPT_FAIL_AS_PROBLEM = True
# RESPONSE_BODY 超过该长度只保留前面部分
RESPONSE_BODY_MAX = 100
# 连续 N 个及以上的 * 视为被打码/加密的字段
ENCRYPTED_STAR_RUN = 6
_STAR_RE = re.compile(r"\*{%d,}" % ENCRYPTED_STAR_RUN)

# 拼对话历史用的 key 及其在一个 span 内的先后顺序
CONV_ORDER = {
    "prompt": 1, "function_name": 2, "skill_name": 3,
    "response_text": 4, "function_args": 5, "response_body": 6,
}

AGENT_CENTER_URL = (
    "https://apigw-cn-south02.huawei.com/api/agentPortalService/external/v1/common/"
    "203c0290-3227-4aa1-bb00-dccb3455b170/mate_api"
)

DEFAULT_SCENE = "skill_extraction_admission"
REQUEST_TIMEOUT = 30000  # Agent Center 处理较慢，给足超时

# 规则过滤阈值 / 标记
MIN_CONVERSATION_LENGTH = 3000
PROMPT_PREFIX = "[PROMPT]"
TOOL_CALL_MARKERS = ("[FUNCTION]", "function_name", "[TOOL]", "[MCP]")

MIN_PROMPT_COUNT = 2

SESSION_KEEP_KEYS = [
    'function_args', 'function_name', 'prompt',
    'reasoning_text', 'request_text', 'response_body', 'response_text',
    'result_status', 'skill_name',
    'ide_type', 'remote_git_repo_path',  # event_name=config 时才有，用于补 IDE / 代码仓
]

CHUNK = 10  # 每批拉多少个 session 的行
READ_WORKERS = 3  # 读库并发
UPSERT_BATCH = 20  # 攒多少条 summary 写一次

SESSION_MAX_BYTES = 50 * 1024 * 1024  # 单 session 全部 value 超 50MB 不拉
SESSION_MAX_ROWS = 50000  # 或行数超 5 万不拉
