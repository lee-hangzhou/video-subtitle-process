from fastapi import APIRouter

from app.schemas.base import Response
from app.schemas.task import CancelTaskReq, SubmitTaskReq, SubmitTaskResp, TaskDetailReq, TaskDetailResp
from app.services import registry

router = APIRouter()


@router.post("/submit")
async def submit_task(req: SubmitTaskReq) -> Response[SubmitTaskResp]:
    local_task_id = await registry.task_service.submit_task(req)
    return Response(data=SubmitTaskResp(local_task_id=local_task_id))


@router.post("/cancel")
async def cancel_task(req: CancelTaskReq) -> Response[None]:
    await registry.task_service.cancel_task(req)
    return Response()


@router.post("/detail")
async def task_detail(req: TaskDetailReq) -> Response[TaskDetailResp]:
    task = await registry.task_service.get_task(req)
    return Response(data=TaskDetailResp(
        cloud_task_id=task.cloud_task_id,
        task_type=task.task_type,
        status=task.status,
        input_files=task.input_files or [],
        output_files=task.output_files or [],
        error_message=task.error_message,
        created_at=task.created_at.isoformat(),
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    ))
