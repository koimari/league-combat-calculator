"""The one stop every interpreter in this package raises.

A ``ValueError``, because a declaration that cannot answer its interpreter's
question is a bad value. Nothing catches it: the message is the whole
content, and every message names the mechanic that failed rather than the
module that noticed.
"""

from __future__ import annotations


class InterpretationError(ValueError):
    """A declaration cannot answer what its interpreter asked of it."""
