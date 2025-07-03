# app/logger.py

import sys
from loguru import logger
from app.config import settings

# Remove any pre-configured handlers (especially the default one)
logger.remove()

# Add a handler that writes to stderr at the level specified in settings.log_level
logger.add(
    sys.stderr,
    level=settings.log_level,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}"
)
