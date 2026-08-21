"""FastAPI app factory: CORS, router mounting, unified error contract."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import analytics, booking, chat, health, session
from app.config import get_settings
from app.exceptions import AppError
from app.models.responses import ErrorResponse


def _error_body(error_code: str, message: str, retryable: bool) -> dict[str, str | bool]:
    return ErrorResponse(error_code=error_code, message=message, retryable=retryable).model_dump()


def _format_validation_message(exc: RequestValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(item) for item in error.get("loc", ()) if item != "body")
        msg = error.get("msg", "Invalid value")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) or "Request validation failed."


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="Northstar Homes AI Sales Agent", version="0.1.0")

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health.router, prefix="/api", tags=["health"])
    application.include_router(chat.router, prefix="/api", tags=["chat"])
    application.include_router(booking.router, prefix="/api", tags=["booking"])
    application.include_router(session.router, prefix="/api", tags=["session"])
    application.include_router(analytics.router, prefix="/api", tags=["analytics"])

    @application.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.error_code, exc.message, exc.retryable),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body("VALIDATION_ERROR", _format_validation_message(exc), False),
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("INTERNAL_ERROR", detail, False),
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, (HTTPException, StarletteHTTPException, AppError, RequestValidationError)):
            raise exc
        return JSONResponse(
            status_code=500,
            content=_error_body(
                "INTERNAL_ERROR",
                str(exc) or "An unexpected error occurred.",
                False,
            ),
        )

    return application


app = create_app()
