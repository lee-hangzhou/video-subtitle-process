import os
import sys

from celery.__main__ import main

IS_DARWIN = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

if IS_DARWIN:
    # macOS (arm64) 上 Celery prefork + PaddleOCR 会因 fork 后
    # Apple Accelerate/OMP 线程安全检查触发 SIGSEGV
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

# Worker:
#   python worker.py
# Beat:
#   celery -A app.core.celery_app beat --loglevel=info

sys.argv = [
    "celery",
    "-A",
    "app.core.celery_app",
    "worker",
    "--loglevel=info",
]

if IS_DARWIN:
    # macOS 用 solo 池，彻底避免 fork 安全问题；多路并发通过启动多个 worker 进程实现
    sys.argv += ["--pool=solo"]
elif IS_WINDOWS:
    # Windows 不支持 fork，Celery 会用 spawn 模式；
    # 默认 concurrency=CPU核数，对 OCR/ASR 重任务来说太多，限制为 2
    sys.argv += ["--pool=solo", "--concurrency=2"]

main()
