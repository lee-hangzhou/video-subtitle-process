import asyncio

from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown
from tortoise import Tortoise
from tortoise.exceptions import OperationalError as TortoiseOperationalError

from app.core.config import settings
from app.core.database import db
from app.core.logger import logger

celery_app = Celery(
    "video-subtitle-process",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.process"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    beat_schedule={
        "poll-erase-tasks": {
            "task": "app.tasks.process.poll_erase_tasks",
            "schedule": 60.0,
        },
    },
)

_worker_loop: asyncio.AbstractEventLoop | None = None


@worker_process_init.connect
def _on_worker_init(**_):
    """Worker 进程启动时，建立持久事件循环并初始化 DB 连接池。"""
    global _worker_loop
    _worker_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_worker_loop)
    _worker_loop.run_until_complete(db.connect())
    logger.info("Celery worker initialized: DB connected")


@worker_process_shutdown.connect
def _on_worker_shutdown(**_):
    """Worker 进程退出时，关闭 DB 连接池和事件循环。"""
    assert _worker_loop is not None
    _worker_loop.run_until_complete(db.disconnect())
    _worker_loop.close()
    logger.info("Celery worker shutdown: DB disconnected")


async def _ensure_db_connection() -> None:
    """执行任务前 ping DB，连接丢失时自动重连。"""
    try:
        connection = Tortoise.get_connection("default")
    except KeyError:
        return

    try:
        await connection.execute_query("SELECT 1")
    except TortoiseOperationalError:
        logger.warning("DB connection lost, reconnecting...")
        try:
            await connection.close()
        except Exception:
            pass
        await connection.create_connection(with_db=True)
        logger.info("DB reconnected")


def run_in_worker(coro):
    """在 Worker 持久事件循环中运行协程，执行前自动检查 DB 连接。"""
    if _worker_loop is None:
        raise RuntimeError("Celery worker loop not initialized")

    async def _runner():
        await _ensure_db_connection()
        return await coro

    return _worker_loop.run_until_complete(_runner())
