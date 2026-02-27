from tortoise import fields
from tortoise.models import Model


class Task(Model):
    id = fields.BigIntField(pk=True)
    cloud_task_id = fields.BigIntField(unique=True, description="翻译平台任务ID")
    task_type = fields.SmallIntField(description="任务类型：1=提取 2=擦除 3=压制 4=转码")
    status = fields.SmallIntField(default=1, description="状态：1=待处理 2=处理中 3=成功 4=失败 5=已取消")
    input_files = fields.JSONField(default=list, description="输入文件OSS key列表")
    output_files = fields.JSONField(default=list, description="输出文件OSS key列表")
    params = fields.JSONField(null=True, description="任务参数")
    celery_task_id = fields.CharField(max_length=255, null=True, description="Celery任务ID")
    callback_url = fields.CharField(max_length=500, null=True, description="完成回调地址")
    error_message = fields.TextField(null=True, description="错误信息")
    started_at = fields.DatetimeField(null=True, description="开始处理时间")
    completed_at = fields.DatetimeField(null=True, description="完成时间")
    created_at = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_at = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "task"
        indexes = [('cloud_task_id',), ('task_type',), ('status',), ('created_at',)]
