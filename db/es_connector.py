import ssl
from typing import Dict
from functools import lru_cache
from elasticsearch import Elasticsearch
from elasticsearch_dsl import connections

from project_configs.settings import EsConfig, ES_HOSTS, ES_USERNAME, ES_PASSWORD
from utils.decrypt import kms_decrypt
from project_configs.env_config import APP_ENV, NAMO_ENV_LIST


class EsConnector:

    def __init__(self, hosts, user_name, passwd, custom_config: Dict):
        self.hosts = hosts
        self.custom_config = custom_config
        self.client = Elasticsearch(hosts, scheme="http", http_auth=(user_name, passwd), verify_certs=False)
        self.search_cursor = self._get_custom_search()
        connections.add_connection("default", self.client)

    def _get_custom_search(self):
        """创建自定义的search对象"""
        original_search = self.client.search

        def custom_search(*args, **kwargs):
            for key, value in self.custom_config.items():
                kwargs.setdefault(key, value)  # 设置默认值
            return original_search(*args, **kwargs)

        self.client.search = custom_search
        return self.client


@lru_cache(maxsize=128)
def get_es_connector() -> EsConnector:
    # 按环境判断是否解密
    if APP_ENV in NAMO_ENV_LIST:
        es_host = EsConfig.HOST
        es_user = EsConfig.USERNAME
        es_pwd = EsConfig.PASSWORD
    else:
        es_host = kms_decrypt(EsConfig.HOST)
        es_user = kms_decrypt(EsConfig.USERNAME) if EsConfig.USERNAME else ""
        es_pwd = kms_decrypt(EsConfig.PASSWORD) if EsConfig.PASSWORD else ""
    es_port = EsConfig.PORT
    es_connector = EsConnector(
        [{"host": es_host, "port": es_port}],
        es_user,
        es_pwd,
        EsConfig.DEFAULT_Config
    )
    return es_connector


if APP_ENV not in NAMO_ENV_LIST:
    context = getattr(ssl, "_create_unverified_context")()
    AI_test_es_client = Elasticsearch(
        ES_HOSTS,
        http_auth=(ES_USERNAME, kms_decrypt(ES_PASSWORD)),
        scheme="https",
        ssl_context=context,
    )
else:
    AI_test_es_client = None
