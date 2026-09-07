import time
from urllib.parse import quote_plus

from sqlalchemy import create_engine, event
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.orm import sessionmaker

from constants import DB_TYPE_GAUSSDB, DB_TYPE_MYSQL
from logger import logger
from project_configs.env_config import APP_ENV, NAMO_ENV_LIST
from project_configs.settings import ModelAnalyiseSQLConfig
from utils.decrypt import kms_decrypt

# 全局变量：按 db_key 缓存多个 SqlConnector 实例
_sql_connector_instances = {}


# ========== 自定义 GaussDB 方言 ==========
class GaussDBDialect(PGDialect_psycopg):
    """GaussDB 方言，跳过版本解析"""
    name = 'gaussdb'

    def _get_server_version_info(self, connection):
        # GaussDB 版本字符串无法被标准解析，返回一个兼容的假版本
        # GaussDB 基于 PostgreSQL 9.2，这里返回 (9, 2, 0)
        return (9, 2, 0)


# 注册自定义方言
registry.register("postgresql.gaussdb", "db.sql_connector", "GaussDBDialect")


class SqlConnector:
    """统一数据库连接器，支持 MySQL 和 GaussDB"""

    def __init__(self, host, port, user, passwd, dbname, db_type=DB_TYPE_MYSQL, schema="co_mlops"):
        self.db_type = db_type
        self.schema = schema

        if db_type == DB_TYPE_GAUSSDB:
            # GaussDB - 使用自定义方言
            self.database_url = (
                f"postgresql+gaussdb://{quote_plus(user)}:{quote_plus(passwd)}"
                f"@{host}:{port}/{dbname}"
            )
            # 设置默认 schema（不同的库可以传入不同的 schema）
            if schema:
                self.database_url += f"?options=-csearch_path%3D{schema}"
        else:
            # MySQL
            self.database_url = (
                f'mysql+pymysql://{quote_plus(user)}:{quote_plus(passwd)}'
                f'@{host}:{port}/{dbname}'
            )

        engine_kwargs = {
            "pool_size": 10,
            "max_overflow": 5,
            "pool_timeout": 30,
            "pool_recycle": 1800,
            "pool_pre_ping": True,
            "echo": False,
        }

        self.engine = create_engine(self.database_url, **engine_kwargs)
        self.session_local = sessionmaker(bind=self.engine)
        self._setup_sql_logging()

    @property
    def client(self):
        return self.session_local()

    def _setup_sql_logging(self):
        """设置 SQL 查询日志"""

        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            context.query_start_time = time.time()

        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            total = time.time() - context.query_start_time
            logger.debug(f"[{self.db_type.upper()}] [Time] {total:.6f} 秒， [SQL] {statement[:500]}")

        event.listen(self.engine, "before_cursor_execute", before_cursor_execute)
        event.listen(self.engine, "after_cursor_execute", after_cursor_execute)


def get_sql_connector(config=None, schema="co_mlops", db_key=None) -> SqlConnector:
    """获取数据库连接（多实例单例：按 db_key 缓存）

    - NAMO 环境: 直接使用配置中的明文账号密码
    - 其他环境: 账号密码需要 kms 解密
    - 通过传入不同的 config / schema 即可连接多个不同的 GaussDB

    用法：
        conn1 = get_sql_connector()                                   # 默认库
        conn2 = get_sql_connector(config=OtherSQLConfig, schema="xxx")  # 第二个库
    """
    global _sql_connector_instances

    if config is None:
        config = ModelAnalyiseSQLConfig

    # 用 db_key 区分不同的连接；不传时根据连接信息自动生成唯一 key
    if db_key is None:
        db_key = f"{config.host}:{config.port}/{config.dbname}/{schema}"

    # 已经创建过就直接复用
    if db_key in _sql_connector_instances:
        return _sql_connector_instances[db_key]

    is_namo_env = APP_ENV in NAMO_ENV_LIST
    logger.info(f"[{APP_ENV}] 使用 GaussDB 连接: {db_key}")

    user = config.user
    passwd = config.passwd
    if not is_namo_env:
        # 非 NAMO 环境账号密码需要解密
        user = kms_decrypt(user)
        passwd = kms_decrypt(passwd)

    connector = SqlConnector(
        host=config.host,
        port=config.port,
        dbname=config.dbname,
        user=user,
        passwd=passwd,
        db_type=DB_TYPE_GAUSSDB,
        schema=schema,
    )

    _sql_connector_instances[db_key] = connector
    return connector
