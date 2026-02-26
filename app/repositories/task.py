from app.models.task import Task
from app.repositories.base import BaseRepository
from app.schemas.task import TaskStatus, TaskType


class TaskRepository(BaseRepository[Task]):
    def __init__(self) -> None:
        self.model = Task

    async def create_task(
            self,
            cloud_task_id: int,
            task_type: TaskType,
            input_files: list[str],
            params: dict = None,
            callback_url: str = None,
    ) -> Task:
        """创建任务记录。"""
        return await self.create(
            cloud_task_id=cloud_task_id,
            task_type=task_type,
            input_files=input_files,
            params=params,
            callback_url=callback_url,
        )

    async def get_by_cloud_task_id(self, cloud_task_id: int) -> Task | None:
        """按翻译平台任务ID查询。"""
        return await self.model.filter(cloud_task_id=cloud_task_id).first()

    async def update_status(self, task_id: int, status: TaskStatus) -> Task | None:
        """更新任务状态。"""
        return await self.update(task_id, status=status)

    async def get_processing_erase_tasks(self) -> list[Task]:
        """查询所有处理中的擦除任务，供 QuVideo 轮询使用。"""
        return await self.model.filter(
            task_type=TaskType.ERASE,
            status=TaskStatus.PROCESSING,
        ).all()
