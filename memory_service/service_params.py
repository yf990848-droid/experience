from datetime import datetime
from typing import List, Dict, Optional, Union, Any
from pydantic import BaseModel, Field


# 定义消息模型
class QueryPara(BaseModel):
    session_id: str
    create_time: Optional[float] = None
    top_k: int = 5
    post_process: Optional[bool] = None
    open_long_term: bool = False

    enable_compression: bool = Field(
        default=True,
        description="是否启用多轮对话压缩"
    )


class FunctionCall(BaseModel):
    name: str
    arguments: Optional[Dict[str, Any]] = None


class ToolCall(BaseModel):
    partial: bool
    id: Optional[str] = None
    tool_name: Optional[str] = None
    arguments: Optional[str] = None


class Think(BaseModel):
    partial: bool
    reasoning_content: Optional[str] = None

    class Config:
        extra = "allow"  # 允许出现未在模型中声明的字段


class Answer(BaseModel):
    partial: bool
    result: Optional[str] = None

    class Config:
        extra = "allow"  # 允许出现未在模型中声明的字段


class AgentTransfer(BaseModel):
    partial: bool
    agent_name: Optional[str] = None
    new_task: Optional[str] = None

    class Config:
        extra = "allow"  # 允许出现未在模型中声明的字段


class Ask(BaseModel):
    partial: bool
    question: Optional[str] = None

    class Config:
        extra = "allow"  # 允许出现未在模型中声明的字段


class Statistic(BaseModel):
    partial: bool
    token_usage: Optional[Dict] = None

    class Config:
        extra = "allow"  # 允许出现未在模型中声明的字段


class Message(BaseModel):
    index: Optional[int] = None
    model_id: Optional[str] = None
    agent_id: Optional[str] = None
    role: str
    create_time: float  # 时间戳
    content: str
    content_hash_code: Optional[str] = None  # 内容的hash值
    memory: List[str] = []
    function_call: Optional[Union[FunctionCall, Dict]] = None
    is_cancel: bool = False
    is_delete: bool = False  # 是否已删除
    error_code: int = 0
    delegate_action: Optional[Dict] = None
    delegate_observation: Optional[Dict] = None
    delegate_session_id: Optional[str] = None
    is_compress: Optional[bool] = False
    original_content: Optional[str] = None  # 压缩前的原始内容备份
    compress_type: Optional[str] = None  # 压缩类型，如 "file_operation"

    # 新增字段，默认 None（即未赋值时序列化为 null）
    tool_call: Optional[ToolCall] = None
    think: Optional[Think] = None
    answer: Optional[Answer] = None
    agent_transfer: Optional[AgentTransfer] = None
    ask: Optional[Ask] = None
    statistic: Optional[Statistic] = None

    error: Optional[str] = None
    author: Optional[str] = None
    tool_call_id: Optional[str] = None


# 定义请求模型
class ChatRequest(BaseModel):
    session_id: str
    user_id: str
    scene: Optional[str] = "common"
    messages: List[Message]
    delete_last_message: Optional[bool] = False  # 是否删除最后一条消息


class SessionPrompt(BaseModel):
    session_id: str
    system_prompt: str = ""


class InitialSession(BaseModel):
    session_id: str
    agent_id: str = ""
    agent_name: str = ""
    agent_description: str = ""
    parent_session_id: Optional[str] = None


class SessionPropertyPara(BaseModel):
    session_id: str
    user_id: Optional[str] = None


class HistoryIndexParam(BaseModel):
    session_id: str
    indices: Optional[List[int]] = None


class LongTextSaveParam(BaseModel):
    session_id: Optional[str]
    text: str


class SessionMemoriesQueryParam(BaseModel):
    session_id: str


class LongTermMemoriesQueryParam(BaseModel):
    session_id: str
    page_size: int
    cur_page_id: int


class MemoryQueryParam(BaseModel):
    memory_id: str


class SessionQueryByAgentParam(BaseModel):
    agent_id: str
    page_size: int
    cur_page_id: int


class SaveRequest(BaseModel):
    summary: Optional[str] = ""
    content: Optional[str] = ""
    gist_data: List[dict]


class BatchGetRequest(BaseModel):
    content_id: str
    gist_index_list: List[int]


class SemanticSearchRequest(BaseModel):
    content_id: str
    query: str
    token_limits: int = 3072


class CompressContentRequest(BaseModel):
    session_id: str
    content_hash_id: str
    content: str


class AgentRouterRequest(BaseModel):
    user_query: str
    user_id: str


class ProductInfo(BaseModel):
    pdu_name: Optional[Union[str, List[str]]] = None  # 支持单个或多个部门
    pdu_code: Optional[str] = None
    product_name: Optional[str] = None
    version_name: Optional[str] = None


class DocumentCreate(BaseModel):
    scene_id: str
    doc_id: Optional[str] = None
    title: str
    summary: str
    user_id: str
    experience: Optional[str] = None
    rag_search_text: Optional[str] = None
    product: Optional[ProductInfo] = None
    metadata: Optional[Dict[str, Any]] = None
    log: Optional[Dict[str, Any]] = None
    scene: Optional[str] = None


class DocumentUpdate(BaseModel):
    search_texts: Optional[Dict[str, str]] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    experience: Optional[str] = None
    rag_search_text: Optional[str] = None
    product: Optional[ProductInfo] = None
    metadata: Optional[Dict[str, Any]] = None
    log: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None
    scene: Optional[str] = None


class SearchWeights(BaseModel):
    vector: float = 0.7
    bm25: float = 0.3


class SearchRequest(BaseModel):
    scene_id: Optional[Union[str, List[str]]] = None
    query: str
    top_k: int = Field(default=10, ge=1, le=500)
    weights: Optional[SearchWeights] = None
    product: Optional[ProductInfo] = None
    filter: Optional[Dict[str, Any]] = None
    score_threshold: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    search_field: str = Field(default="title",
                              description="指定检索字段，可选: title, summary, experience, rag_search_text")
    user_id: Optional[str] = None
    doc_id: Optional[str] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=1000)
    scene: Optional[Union[str, List[str]]] = None
    quality_only: bool = Field(default=False, description="是否只检索高质量文档")
    caller_id: Optional[str] = None


class SearchByFilter(BaseModel):
    scene_id: Optional[Union[str, List[str]]] = None
    product: Optional[ProductInfo] = None
    filter: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None
    doc_id: Optional[str] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=10, ge=1, le=1000)
    sort: Optional[List[Dict[str, Any]]] = None
    scene: Optional[Union[str, List[str]]] = None
    quality_only: Optional[bool] = False
    caller_id: Optional[str] = None


class MessageReplaceItem(BaseModel):
    """单条替换项：通过 index 定位 session 内的消息"""
    index: int
    content: Optional[str] = None
    original_content: Optional[str] = None
    is_compress: Optional[bool] = True
    compress_type: Optional[str] = None


class HistoryReplaceRequest(BaseModel):
    """批量替换 session 消息的请求体"""
    session_id: str
    messages: List[MessageReplaceItem]


class SceneCountRequest(BaseModel):
    scene_mapper: Optional[Dict[str, Any]] = None  # 由调用方(EMS)传入的场景树
    scene_id: Optional[str] = None
    product: Optional[Any] = None
    user_id: Optional[str] = None


class UsageStatsRequest(BaseModel):
    start_time: datetime
    end_time: datetime
    only_success: Optional[bool] = None  # None=全部, True=仅成功, False=仅失败
