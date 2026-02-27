import os
import sys

from celery.__main__ import main

IS_DARWIN = sys.platform == "darwin"

if IS_DARWIN:
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

sys.argv = [
    "celery",
    "-A",
    "app.core.celery_app",
    "beat",
    "--loglevel=info",
]



main()
