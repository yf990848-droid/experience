import os
import tiktoken
from project_configs.settings import CompressConfig
from utils.decorator import timing_decorator

current_dir_path = os.path.dirname(os.path.abspath(__file__))
tiktoken_cache_dir = os.path.join(current_dir_path, "..", "resource", "tiktoken_models")
os.environ["TIKTOKEN_CACHE_DIR"] = tiktoken_cache_dir

encodings = tiktoken.get_encoding('cl100k_base')


def token_count(content: str) -> int:
    return len(encodings.encode(content))


@timing_decorator("-" * 50)
def is_long_text(content: str, threshold: int = CompressConfig.TOKEN_THRESHOLD) -> bool:
    length = len(encodings.encode(content))
    return length > threshold
