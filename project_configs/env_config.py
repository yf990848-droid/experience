import logging
import os
from pathlib import Path
from typing import Dict, Any

from dotenv import load_dotenv
from pydantic import field_validator, ValidationInfo
from pydantic_settings import BaseSettings  # BaseSettings从pydantic-settings导入

# 导入项目已有模块
from utils.decrypt import get_decrypt_text
from exception.exceptions import ProjectException
from logger import logger

# 1. 读取并规范化 PUBLISH_TYPE
APP_ENV = os.path.basename(os.getenv("PUBLISH_TYPE", "").lower())
namo_settings = None  # 全局namo配置实例，供settings.py调用

# 2. 仅处理namo环境
NAMO_ENV_LIST = ["namo-beta", "namo-prod"]
if APP_ENV in NAMO_ENV_LIST:
    # 构建.env配置文件路径
    env_dir = Path(__file__).resolve().parent.parent / "env"
    env_filename = env_dir / f".env.{APP_ENV}"

    # 配置文件不存在时，抛namo专属异常
    if not os.path.exists(env_filename):
        logger.error(f"未找到namo配置文件：{env_filename}")
        raise ProjectException(
            error_code=ProjectException.NAMO_CONFIG_NOT_FOUND_ERROR,
            filename=str(env_filename)
        )

    # 加载.env文件
    load_dotenv(dotenv_path=env_filename, override=True, verbose=True)


    # 定义namo配置类（仅包含settings.py需要的字段）
    class NamoSettings(BaseSettings):
        # MySQL配置（对应settings.py的NamoModelAnalyiseSQLConfig）
        DB_HOST: str
        DB_PORT: int
        DB_USER: str
        DB_PASSWORD: str
        DB_NAME: str
        PIPELINE_MAIN_SCRIPT: str = ""
        # ES配置（对应settings.py的NamoEsConfig）
        ES_HOST: str
        ES_PORT: int
        ES_INDEX: str = "session_history"
        # redis
        REDIS_HOST: str
        REDIS_PORT: int

        @field_validator('*', mode='before')
        @staticmethod
        def decrypt_sensitive_fields(value, info: ValidationInfo):
            """自动解密AES@密文（适配pydantic 2.x）"""
            key = info.field_name
            # 仅对以AES@开头的字符串解密
            if isinstance(value, str) and value.startswith("AES@"):
                decrypted = get_decrypt_text(value[4:])

                # 解密失败：utils 里约定失败时返回原 ciphertext
                if decrypted == value[4:]:
                    logger.error(f"namo密文解密失败（key={key}）")
                    raise ProjectException(
                        error_code=ProjectException.NAMO_DECRYPT_FAILED_ERROR,
                        key=key
                    )
                return decrypted
            return value


    # 创建配置实例，失败时抛配置加载异常
    try:
        namo_settings = NamoSettings()
        logger.info(f" namo {APP_ENV} 配置加载成功")
    except ValueError as e:
        logger.error(f" namo配置加载失败：{e}")
        raise ProjectException(
            error_code=ProjectException.NAMO_CONFIG_LOAD_FAILED_ERROR,
            msg=str(e)
        )
