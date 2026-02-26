import sys
from celery.__main__ import main

# Worker:
#   python worker.py
#   celery -A app.core.celery_app worker --loglevel=info --concurrency=4
#
# Beat:
#   celery -A app.core.celery_app beat --loglevel=info

sys.argv = [
    "celery",
    "-A", "app.core.celery_app",
    "worker",
    "--loglevel=info",
    "--concurrency=4",
]

main()
