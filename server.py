import uvicorn

from core.app_config import app
from project_configs.settings import ServerConfig
from logger import logger


def main():
    logger.info("Starting plugin service...")
    uvicorn.run(
        "core.app_config:app",
        host=ServerConfig.DEFAULT_HOST_IP,
        port=ServerConfig.DEFAULT_PORT,
        log_level=logger.level,
        access_log=True,
        workers=4
    )


if __name__ == "__main__":
    from db_operate.sql_models import init_sql
    from db_operate.es_models import init_es
    init_sql()
    init_es()

    main()
