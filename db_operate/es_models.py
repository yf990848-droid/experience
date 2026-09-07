import time
from typing import List
from elasticsearch_dsl import Document, Date, Keyword, Text, Float, Integer, DenseVector, Boolean

from constants import DIM_384
from project_configs.settings import EsConfig
from utils import common_utils


class SystemPrompt(Document):
    session_id = Keyword()
    create_time = Float()
    system_prompt = Text()

    class Index:
        name = EsConfig.SYSTEM_PROMPT_INDEX

    def save(self, **kwargs):
        if not self.create_time:
            self.create_time = time.time()
        return super().save(**kwargs)


class CompressedContentChunkBase(Document):
    """公共基类：压缩内容分片的共有字段与方法。

    包含字段：
      - compress_content_id
      - chunk_id, previous_chunk_id, next_chunk_id
      - start_line, end_line
      - content
      - created_at

    子类必须定义自身的 Index.name。
    """

    # 基础字段
    compress_content_id = Keyword()  # 压缩内容ID
    chunk_id = Integer()  # 分片ID
    previous_chunk_id = Integer()  # 上一个分片ID
    next_chunk_id = Integer()  # 下一个分片ID

    # 文本位置信息
    start_line = Integer()  # 起始行号
    end_line = Integer()  # 结束行号

    # 内容字段
    content = Text()  # 实际内容

    # 时间戳
    created_at = Date()  # 创建时间

    @classmethod
    def get_index_name(cls):
        """返回索引名称，由每个子类的 `class Index: name = ...` 提供。"""
        try:
            return cls.Index.name  # type: ignore[attr-defined]
        except Exception as e:  # pragma: no cover
            raise NotImplementedError(
                f"{cls.__name__} 必须定义内部类 Index 并提供 name 属性"
            ) from e


class TextCompressedContentChunk(CompressedContentChunkBase):
    """Elasticsearch 文本类，记录压缩内容的分片信息"""

    vector = DenseVector(dims=DIM_384)  # 模型向量维度如384

    class Index:
        name = "text_compressed_content_chunks"  # 索引名称

    def __str__(self):
        return (
            f"TextCompressedContentChunk(compress_content_id={self.compress_content_id}, "
            f"chunk_id={self.chunk_id}, lines={self.start_line}-{self.end_line})"
        )


class MarkdownCompressedContentChunk(CompressedContentChunkBase):
    """Elasticsearch Markdown类，记录压缩内容的分片信息"""

    vector = DenseVector(dims=DIM_384)  # 模型向量维度如384

    # 标题相关字段（无索引）
    titles = Keyword(index=False)  # 父级标题列表
    include_titles = Keyword(index=False)  # 包含子标题的标题列表

    class Index:
        name = "markdown_compressed_content_chunks"  # 索引名称

    def __str__(self):
        return (
            f"MarkdownCompressedContentChunk(compress_content_id={self.compress_content_id}, "
            f"chunk_id={self.chunk_id}, lines={self.start_line}-{self.end_line})"
        )


class CodeCompressedContentChunk(CompressedContentChunkBase):
    """Elasticsearch 代码类，记录压缩内容的分片信息"""

    chunk_type = Keyword()  # 代码块类型
    language = Keyword()  # 代码块语言
    symbol_name = Text()  # 代码块符号名称
    parent_symbol = Keyword()  # 父代码块符号名称
    signature = Text()  # 代码块签名
    calls = Keyword(multi=True)  # 调用的代码块符号名称列表
    content = Text()  # 实际内容（如需覆盖父类映射配置，此行可保留）
    vector = DenseVector(dims=DIM_384)  # 模型向量维度如384

    class Index:
        name = "code_compressed_content_chunks"  # 索引名称

    def __str__(self):
        return (
            f"CodeCompressedContentChunk(compress_content_id={self.compress_content_id}, "
            f"chunk_id={self.chunk_id}, lines={self.start_line}-{self.end_line})"
        )


class JsonCompressedContentChunk(CompressedContentChunkBase):
    """Elasticsearch JSON类，记录压缩内容的分片信息"""

    vector = DenseVector(dims=DIM_384)  # 模型向量维度如384

    class Index:
        name = "json_compressed_content_chunks"  # 索引名称

    def __str__(self):
        return (
            f"JsonCompressedContentChunk(compress_content_id={self.compress_content_id}, "
            f"chunk_id={self.chunk_id}, lines={self.start_line}-{self.end_line})"
        )


class MemoryNote(Document):
    """
    Elasticsearch Document 映射：
    表示一个记忆节点，带有关键词、标签、时间戳、是否完成等属性。
    """

    keywords = Keyword(multi=True)
    tags = Keyword(multi=True)

    # 系统字段，用字符串类型存储 YYYY-MM-DD（由 timestamp 派生）
    create_date = Keyword()

    category = Keyword()
    layer_category = Keyword()
    completion = Boolean()
    connect_notes = Keyword(multi=True)
    connect_histories = Keyword(multi=True)
    vector = DenseVector(dims=384)

    content = Text()
    detail = Text()

    class Index:
        name = EsConfig.LONGTERM_MEMORY_INDEX  # 可根据需求自定义索引名

    def __init__(
            self, meta=None,
            *, scene: str = None, keywords: List[str] = None, tags: List[str] = None,
            timestamp: float = None, category: str = None, layer_category: str = None,
            completion: bool = None, connect_notes: List[str] = None, connect_histories: List[str] = None,
            content: str = None, detail: str = None, **kwargs
    ):
        super().__init__(meta=meta, **kwargs)
        self.scene = scene
        self.keywords = keywords or []
        self.tags = tags or []
        self.create_date = common_utils.timestamp2ymd(timestamp) if timestamp else None
        self.category = category
        self.layer_category = layer_category
        self.completion = completion
        self.connect_notes = connect_notes or []
        self.connect_histories = connect_histories or []
        self.content = content
        self.detail = detail

    @classmethod
    def get_index_name(cls):
        return cls.Index.name


def init_es():
    from db.es_connector import get_es_connector
    get_es_connector()
    MarkdownCompressedContentChunk.init()
    CodeCompressedContentChunk.init()
    TextCompressedContentChunk.init()
    JsonCompressedContentChunk.init()


if __name__ == '__main__':
    init_es()
