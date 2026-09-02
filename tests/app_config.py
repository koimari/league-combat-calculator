"""One home for the process-global Flask config the route tests borrow.

``src.app.app`` is a module-level singleton, so a test that flips
``TESTING`` or ``RATE_LIMIT_ENABLED`` flips it for every later test in the
session -- test_app.py's rate-limit tests need ``TESTING`` false, because
the limiter is bypassed under it.  Borrowing a key through this is what
puts the old value back.

``mock.patch.dict`` rather than a hand-written save/restore, because a key
Flask defaults to ``None`` cannot be saved with ``config.get``: absent and
present-as-``None`` read the same, and putting ``None`` back as *absent*
deletes it.  ``PROPAGATE_EXCEPTIONS`` is such a key, and Flask reads it by
subscript (``app.py`` ``handle_exception``), so a delete turns the next
route error on this worker into ``KeyError: 'PROPAGATE_EXCEPTIONS'``.
Restoring the whole mapping also puts back what the block changed outside
*overrides*, which is what a test driving a script wants.

This is a test helper, not a test module: it holds no assertions.
"""

import contextlib
from unittest import mock

from src import app as app_module


@contextlib.contextmanager
def app_config(**overrides):
    """Hold *overrides* on the shared app config, restoring what was there."""
    with mock.patch.dict(app_module.app.config, overrides) as config:
        yield config
