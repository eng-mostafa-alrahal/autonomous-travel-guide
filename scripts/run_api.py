"""Run the FastAPI app with the correct asyncio loop on Windows."""

from __future__ import annotations

import uvicorn

from app.core.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.ENVIRONMENT == "development",
        loop="app.core.event_loop:selector_loop_factory",
        log_level=settings.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
