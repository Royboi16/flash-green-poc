# app/logger.py

import sys

from loguru import logger

from app.config import settings

logger.remove()

logger.add(
    sys.stderr,
    level=settings.log_level,
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | {message}"
    ),
)
