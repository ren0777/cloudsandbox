from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, extra: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.extra = extra or {}
        self.headers = headers


def not_found(what: str = "resource") -> ApiError:
    return ApiError("not_found", f"{what} not found", 404)


def _rid() -> str | None:
    return structlog.contextvars.get_contextvars().get("request_id")


def error_body(code: str, message: str, **extra: Any) -> dict:
    return {"error": {"code": code, "message": message, "request_id": _rid(), **extra}}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return JSONResponse(error_body(e.code, e.message, **e.extra), e.status, headers=e.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        return JSONResponse(error_body("validation_error", "invalid request",
                                       details=[{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]),
                            422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "http_error")
        return JSONResponse(error_body(code, str(e.detail)), e.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception):
        structlog.get_logger("cloudlabs").error("http.request.failed", error=repr(e), exc_info=e)
        return JSONResponse(error_body("internal_error", "unexpected server error"), 500)
