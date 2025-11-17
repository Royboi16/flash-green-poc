import importlib


def test_logger_importable():
    module = importlib.import_module("app.logger")
    assert hasattr(module, "logger"), "app.logger module should expose a logger"
