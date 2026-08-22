"""One home for the process-global Flask config the route tests borrow.

``src.app.app`` is a module-level singleton, so a test that flips
``TESTING`` or ``RATE_LIMIT_ENABLED`` flips it for every later test in the
session -- test_app.py's rate-limit tests need ``TESTING`` false, because
the limiter is bypassed under it.  Borrowing a key through this is what
puts the old value back.

This is a test helper, not a test module: it holds no assertions.
"""

import contextlib

from src import app as app_module


@contextlib.contextmanager
def app_config(**overrides):
    """Hold *overrides* on the shared app config, restoring what was there."""
    config = app_module.app.config
    previous = {key: config.get(key) for key in overrides}
    config.update(overrides)
    try:
        yield config
    finally:
        for key, value in previous.items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value
