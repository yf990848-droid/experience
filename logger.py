import logging
from logging.handlers import TimedRotatingFileHandler
import time
import traceback
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from project_configs.settings import LogConfig


def setup_logger():
    """设置logger属性，以及打印格式"""
    logging.basicConfig(level=logging.DEBUG)
    my_logger = logging.getLogger()
    my_logger.setLevel(logging.INFO)

    time_handler = TimedRotatingFileHandler(
        filename=LogConfig.LOG_FILE,
        when=LogConfig.WHEN,
        backupCount=LogConfig.BACKUP_COUNT,
        encoding='utf-8',
        utc=True,  # 如果你想按UTC分割，否则按本地时间
    )
    time_handler.suffix = LogConfig.SUFFIX  # 文件名后缀如

    # 设置打印格式、路径等
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    time_handler.setFormatter(formatter)

    my_logger.addHandler(time_handler)
    return my_logger


# 日志中间件，用于记录Fastapi的打印
class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = request.headers.get("X-Request-ID", "")

        # 记录请求信息
        logger.info(
            f"Request started: {request.method} {request.url.path} "
            f"(ID: {request_id})"
        )

        try:
            # 处理请求
            response = await call_next(request)

            # 计算处理时间
            process_time = time.time() - start_time

            # 记录响应信息
            logger.info(
                f"Request completed: {request.method} {request.url.path} "
                f"- Status: {response.status_code} - Time: {process_time:.4f}s "
                f"(ID: {request_id})"
            )

            return response

        except Exception as e:
            # 记录错误信息
            process_time = time.time() - start_time
            logger.error(
                f"Request failed: {request.method} {request.url.path} "
                f"- Error: {str(e)} - Time: {process_time:.4f}s "
                f"(ID: {request_id})"
            )
            logger.error(traceback.format_exc())

            # 重新引发异常，让FastAPI的异常处理器处理
            raise


logger = setup_logger()
