"""FastAPI app factory: CORS, router mounting, global exception handler stub."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import analytics, booking, chat, health, session
from app.config import get_settings


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

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            raise exc
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": str(exc) or "An unexpected error occurred.",
                "retryable": False,
            },
        )

    return application


app = create_app()
