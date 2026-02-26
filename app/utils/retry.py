import asyncio
import inspect
import time
from functools import wraps
from typing import Callable, Type

from app.core import logger
from app.vars.constants import MAX_RETRIES


def retry(
    max_retries: int = MAX_RETRIES,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
    delay_base: int = 2,
) -> Callable:
    def decorator(func: Callable) -> Callable:
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                last_error = None
                for attempt in range(max_retries):
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        last_error = e
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(delay_base ** attempt)
                raise last_error
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                last_error = None
                for attempt in range(max_retries):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_error = e
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        if attempt < max_retries - 1:
                            time.sleep(delay_base ** attempt)
                raise last_error
            return sync_wrapper
    return decorator
