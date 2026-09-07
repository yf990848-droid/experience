import asyncio
import os
from datetime import timedelta, datetime

from clean_data.clean_old_session import clean
from constants import INTERVAL_DAYS, INTERVAL_MINUTES, INTERVAL_HOURS, MEMORY_CLEAN, MEMORY_AND_PROCESS_EXTRACT, \
    ENABLED, RUN_AT_HOUR, RUN_AT_MINUTE, CODE_AGENT_PIPELINE
from logger import logger
from memory_workflow.worker_loop import MemoryExtractWorkerManager, ProcessExtractWorkerManager
from project_configs.settings import TASK_RUNNER_CONFIG, CST
from skill_evolve.trace2skill_pipeline import run_pipeline_once


def get_interval_seconds(cfg):
    days = cfg.get(INTERVAL_DAYS, 0)
    hours = cfg.get(INTERVAL_HOURS, 0)
    minutes = cfg.get(INTERVAL_MINUTES, 0)
    return timedelta(days=days, hours=hours, minutes=minutes).total_seconds()


async def run_memory_and_process_extract(cfg):
    interval = get_interval_seconds(cfg)
    manager_mem = MemoryExtractWorkerManager(max_workers=3)
    manager_proc = ProcessExtractWorkerManager(max_workers=1)

    while True:
        logger.info("[TASK] Running Memory & Process Extract jobs...")
        memory_task = asyncio.create_task(manager_mem.worker_loop())
        process_task = asyncio.create_task(manager_proc.worker_loop())
        await asyncio.gather(memory_task, process_task)
        await asyncio.sleep(interval)


async def run_clean(cfg):
    """周期性运行 clean 任务"""
    interval = get_interval_seconds(cfg)

    while True:
        logger.info("[TASK] Running clean job...")
        clean()
        await asyncio.sleep(interval)


async def run_code_agent_pipeline(cfg):
    """每日东八区固定时刻运行 code-agent flywheel 流水线。"""
    run_hour = cfg.get(RUN_AT_HOUR, 1)
    run_minute = cfg.get(RUN_AT_MINUTE, 0)

    while True:
        # 一律用东八区的"现在"来计算，和服务器本地时区无关
        now = datetime.now(CST)
        next_run = now.replace(hour=run_hour, minute=run_minute,
                               second=0, microsecond=0)
        if next_run <= now:  # 今天该点已过 -> 排到明天
            next_run += timedelta(days=1)
        wait_seconds = (next_run - now).total_seconds()
        logger.info(f"[TASK] Code Agent Pipeline 下次运行(东八区): {next_run}"
                    f"（{wait_seconds:.0f}s 后）")
        await asyncio.sleep(wait_seconds)

        day = (datetime.now(CST).date() - timedelta(days=3)).isoformat()
        logger.info(f"[TASK] Running Code Agent Pipeline for {day} ...")
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, run_pipeline_once, day)
        except Exception:
            logger.exception("[TASK] Code Agent Pipeline 运行失败")


async def main():
    tasks = []

    env = os.environ.get("env", "test")

    if TASK_RUNNER_CONFIG[MEMORY_AND_PROCESS_EXTRACT][ENABLED]:
        tasks.append(run_memory_and_process_extract(TASK_RUNNER_CONFIG[MEMORY_AND_PROCESS_EXTRACT]))

    if TASK_RUNNER_CONFIG[MEMORY_CLEAN][ENABLED]:
        tasks.append(run_clean(TASK_RUNNER_CONFIG[MEMORY_CLEAN]))

    # 测试环境不跑 code-agent flywheel 流水线
    if env != "test" and TASK_RUNNER_CONFIG[CODE_AGENT_PIPELINE][ENABLED]:
        tasks.append(run_code_agent_pipeline(TASK_RUNNER_CONFIG[CODE_AGENT_PIPELINE]))

    if not tasks:
        logger.info("[INFO] No task is enabled in TASK_RUNNER_CONFIG.")
        return

    await asyncio.gather(*tasks)


if __name__ == '__main__':
    # Run the main coroutine with an event loop
    asyncio.run(main())
