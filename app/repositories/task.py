from app.models.task import Task
from app.repositories.base import BaseRepository
from app.schemas.task import TaskStatus


class TaskRepository(BaseRepository[Task]):
    def __init__(self) -> None:
        self.model = Task

    async def create_task(
            self,
            source: str,
            task_name: str,
            input_url: str,
            output_url: str = None,
            title: str = None,
            params: dict = None
    ):
        """创建任务记录。"""
        return await self.create(
            source=source,
            task_name=task_name,
            input_url=input_url,
            output_url=output_url,
            title=title,
            params=params
        )

    async def update_status(self, task_id: int, status: TaskStatus):
        """更新任务状态。"""
        return await self.update(
            task_id,
            status=status
        )

    async def get_pending(self, source: str = None):
        """查询待处理的任务，可按来源过滤。"""
        query = self.model.filter(status__in=[TaskStatus.PENDING, TaskStatus.PENDING])
        if source:
            query = query.filter(Task.source == source)
        return await query.all()

    async def get_success_by_task_name(self, task_name: str):
        """查询指定任务批次下所有成功的任务。"""
        return await self.model.filter(task_name=task_name, status=TaskStatus.SUCCESS).all()
