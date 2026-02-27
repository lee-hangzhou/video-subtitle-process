import os
import sys
from celery.__main__ import main

# macOS (arm64) 上 Celery prefork + PaddleOCR/PaddlePaddle 会因 fork 后
# Apple Accelerate/OMP 线程安全检查触发 SIGSEGV。
# 使用 --pool=solo 让任务在主进程中运行（不 fork），彻底规避 fork 安全问题。
# 多路并发可通过启动多个独立 worker 进程实现，而不是单进程内多并发。
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

# Worker:
#   python worker.py
#   celery -A app.core.celery_app worker --loglevel=info --pool=solo
#
# Beat:
#   celery -A app.core.celery_app beat --loglevel=info

sys.argv = [
    "celery",
    "-A", "app.core.celery_app",
    "worker",
    "--loglevel=info",
    "--pool=solo",
]

main()
