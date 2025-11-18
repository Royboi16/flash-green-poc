import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("API_KEY", "test-key")

import app.db as db
import app.storage as storage


@pytest.fixture(scope="session", autouse=True)
def configure_test_database():
    engine = db.override_engine("sqlite:///:memory:")
    storage.Base.metadata.create_all(engine)
    yield
    engine.dispose()
