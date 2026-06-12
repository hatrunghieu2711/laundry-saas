"""Lỗi nghiệp vụ + handler trả về error format thống nhất (CLAUDE.md).

    { "success": false, "message": "...", "code": "ORDER_NOT_FOUND" }
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    """Lỗi nghiệp vụ có mã ổn định cho client."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _handle_api_error(_: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "message": exc.message, "code": exc.code},
        )
