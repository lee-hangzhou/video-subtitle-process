import os
import sys

from celery.__main__ import main

# macOS (arm64) 上 Celery prefork + PaddleOCR/PaddlePaddle 会因 fork 后
# Apple Accelerate/OMP 线程安全检查触发 SIGSEGV。

IS_DARWIN = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

if IS_DARWIN:
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

# 所有平台统一限制 OpenBLAS / OMP 的线程数，避免过多计算线程争抢资源
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

sys.argv = [
    "celery",
    "-A",
    "app.core.celery_app",
    "worker",
    "--loglevel=info",
]

if IS_DARWIN:
    sys.argv += ["--pool=solo"]
elif IS_WINDOWS:
    sys.argv += ["--pool=solo", "--concurrency=2"]
main()
