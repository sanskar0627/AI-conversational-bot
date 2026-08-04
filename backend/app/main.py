"""FastAPI app factory and router mounting."""

from fastapi import FastAPI

from app.api.routes import analytics, booking, chat, health, session


def create_app() -> FastAPI:
    application = FastAPI(title="Northstar Homes AI Sales Agent", version="0.1.0")

    application.include_router(health.router, prefix="/api", tags=["health"])
    application.include_router(chat.router, prefix="/api", tags=["chat"])
    application.include_router(booking.router, prefix="/api", tags=["booking"])
    application.include_router(session.router, prefix="/api", tags=["session"])
    application.include_router(analytics.router, prefix="/api", tags=["analytics"])

    return application


app = create_app()
