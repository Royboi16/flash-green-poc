"""
flash_green_poc
~~~~~~~~~~~~~~~
Lightweight prototype for flash‑loan‑style energy / futures arbitrage.

Importing `app` sets up:

* global `settings` object (Pydantic)
* colourised Rich logging
* Prometheus default metrics
"""

from importlib.metadata import version, PackageNotFoundError
import logging
from rich.console import Console
from rich.logging import RichHandler

from .config import settings  # noqa: F401  (side‑effect import)

__all__ = ["settings"]

# ---------------------------------------------------------------------
# Package version
# ---------------------------------------------------------------------
try:
    __version__ = version("flash-green-poc")
except PackageNotFoundError:     # editable install
    __version__ = "0.0.0"

# ---------------------------------------------------------------------
# Logging (Rich pretty handler)
# ---------------------------------------------------------------------
_console = Console()
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(console=_console, markup=True)],
)
logger = logging.getLogger(__name__)
logger.info(f"flash_green_poc {__version__} loaded.")
