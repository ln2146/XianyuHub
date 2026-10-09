"""独立 Worker 进程入口：python -m app.workers.main（PROCESS_ROLE=worker）。

负责调度器、IM 长连接网关与订单事件处理；HTTP 接口由 PROCESS_ROLE=api 的进程提供，
两者通过 Redis 集群桥同步事件、实时推送与 IM 操作。数据库迁移由 API 进程负责。
"""

import asyncio
import signal

from loguru import logger

from app import bootstrap
from app.core.config import get_settings
from app.core.db import dispose_engine, init_engine
from app.core.logging import setup_logging


async def run() -> None:
    setup_logging()
    settings = get_settings()
    if settings.process_role != "worker":
        raise SystemExit("Worker 进程需要设置 PROCESS_ROLE=worker")
    init_engine()
    await bootstrap.setup_runtime()
    await bootstrap.start_workers()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    logger.info("Worker 已就绪")
    await stop.wait()
    logger.info("Worker 正在退出")
    await bootstrap.shutdown()
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(run())
