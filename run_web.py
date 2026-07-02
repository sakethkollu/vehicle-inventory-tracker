import argparse

import uvicorn

from vehicle_inventory.core.config import get_settings
from vehicle_inventory.core.logging import configure_logging, get_logger


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Vehicle Inventory Tracker web server (FastAPI/ASGI)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.log_json)
    log = get_logger(__name__)
    log.info("web_starting", host=args.host, port=args.port, database_url=settings.database_url)

    uvicorn.run(
        "vehicle_inventory.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
