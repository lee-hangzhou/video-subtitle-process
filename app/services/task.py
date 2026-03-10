from app.core import logger
from app.core.celery_app import celery_app
from app.exceptions.base import TaskAlreadyExists, TaskAlreadyFinished, TaskNotFound
from app.models.task import Task
from app.repositories.task import TaskRepository
from app.schemas.task import CancelTaskReq, SubmitTaskReq, TaskDetailReq, TaskStatus
from app.tasks.process import process_video_task


class TaskService:
    def __init__(self) -> None:
        self.task_repo = TaskRepository()

    async def submit_task(self, req: SubmitTaskReq) -> int:
        """创建任务记录并入队，返回本地任务ID。"""
        existing = await self.task_repo.get_by_cloud_task_id(req.cloud_task_id)
        if existing:
            raise TaskAlreadyExists

        task = await self.task_repo.create_task(
            cloud_task_id=req.cloud_task_id,
            task_type=req.task_type,
            input_file=req.input_file,
            params=req.params,
            callback_url=req.callback_url,
        )

        logger.info(
            "task_submitted",
            local_task_id=task.id,
            cloud_task_id=req.cloud_task_id,
            task_type=req.task_type,
        )

        celery_result = process_video_task.delay(task.id)
        await self.task_repo.update(task.id, celery_task_id=celery_result.id)

        return task.id

    async def cancel_task(self, req: CancelTaskReq) -> None:
        """取消任务，已处于终态的任务不可取消。"""
        task = await self.task_repo.get_by_cloud_task_id(req.cloud_task_id)
        if not task:
            raise TaskNotFound

        if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise TaskAlreadyFinished

        if task.celery_task_id:
            celery_app.control.revoke(task.celery_task_id, terminate=True)

        await self.task_repo.update_status(task.id, TaskStatus.CANCELLED)

        logger.info("task_cancelled", cloud_task_id=req.cloud_task_id)

    async def get_task(self, req: TaskDetailReq) -> Task:
        """按翻译平台任务ID查询任务，不存在则抛出 TaskNotFound。"""
        task = await self.task_repo.get_by_cloud_task_id(req.cloud_task_id)
        if not task:
            raise TaskNotFound
        return task
