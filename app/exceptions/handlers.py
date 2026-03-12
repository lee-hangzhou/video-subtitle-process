from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import traceback
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logger import logger
from app.exceptions.base import AppError


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning(
        "app_error",
        error_code=exc.code,
        error_message=exc.message,
        path=request.url.path,
        method=request.method,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "data": None,
            "msg": exc.message,
        },
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    logger.warning(
        "validation_error",
        errors=errors,
        path=request.url.path,
        method=request.method,
    )

    return JSONResponse(
        status_code=400,
        content={
            "code": 400,
            "data": None,
            "msg": "Validation error",
        },
    )


async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "data": None,
            "msg": exc.detail or "HTTP error",
        },
    )


async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    tb_str = traceback.format_exc()
    tb_frames = traceback.extract_tb(exc.__traceback__)
    if tb_frames:
        frame = tb_frames[-1]
        exc_location = {
            "filename": frame.filename,
            "module": frame.name,
            "line": frame.lineno,
        }
    else:
        exc_location = None

    logger.error(
        "unhandled_error",
        error_type=type(exc).__name__,
        error_message=str(exc),
        path=request.url.path,
        method=request.method,
        traceback=tb_str,
        exception_location=exc_location,
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "data": None,
            "msg": "Internal server error",
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, generic_error_handler)
