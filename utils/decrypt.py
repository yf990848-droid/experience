"""
加解密工具
"""
import os
import subprocess
import logging
from functools import lru_cache
from base64 import b64encode, b64decode
from cryptography.fernet import Fernet

from project_configs.settings import ServerConfig
from utils.kms import KMSEncryption, KMSDecryption
from logger import logger
from exception.exceptions import ProjectException
from constants import DECRYPT_SECRET_KEYS


#  密钥读取函数
@lru_cache(maxsize=1)
def get_secret_env_info():
    """读取解密密钥环境变量"""
    # 定义密钥字段名
    secret_keys = DECRYPT_SECRET_KEYS
    secret_dict = {}

    # 直接读取对应环境变量
    for key in secret_keys:
        # 直接用字段名作为环境变量名
        secret_value = os.getenv(key)
        if not secret_value:
            logger.error(f"缺少解密密钥环境变量：{key}")
            raise ProjectException(
                error_code=ProjectException.NAMO_DECRYPT_FAILED_ERROR,
                key=key
            )
        secret_dict[key] = secret_value

    return secret_dict


def get_decrypt_text(ciphertext):
    """
    解密
    """
    if not ciphertext:
        logger.warning("namo解密密文为空")
        return ""

    java_exe_path = "java"  # 部署环境用系统java命令
    current_dir = os.path.dirname(os.path.abspath(__file__))  # decrypt.py所在的utils目录
    jar_path = os.path.join(current_dir, "corecd-aes.jar")  # jar包绝对路径

    secret_dict = get_secret_env_info()
    cmd = [
        java_exe_path,
        "-jar",
        jar_path,
        *[secret_dict[key] for key in DECRYPT_SECRET_KEYS],
        ciphertext
    ]

    try:
        child_tag = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf-8'
        )
        child_out, child_err = child_tag.communicate(timeout=10)

        # 解析结果
        decrypt_text = child_out.strip().splitlines()[0] if child_out else ""
        if child_err or not decrypt_text:
            logger.error("解密失败，将返回原密文")
            return ciphertext

        return decrypt_text

    except Exception:
        logger.error("解密失败，将返回原密文")
        return ciphertext


@lru_cache(maxsize=128)
def kms_encrypt(text):
    kms_en = KMSEncryption(ServerConfig.APP_ID)
    return kms_en.encrypt_info(text)


@lru_cache(maxsize=128)
def kms_decrypt(text):
    kms_de = KMSDecryption(ServerConfig.APP_ID)
    return kms_de.decrypt_info(text)


def encrypt(plain_text, key):
    f = Fernet(key)
    encrypted_text = f.encrypt(plain_text.encode())
    return b64encode(encrypted_text).decode('utf-8')


def decrypt(encrypted_text, key):
    f = Fernet(key)
    decrypted_text = f.decrypt(b64decode(encrypted_text))
    return decrypted_text.decode('utf-8')
