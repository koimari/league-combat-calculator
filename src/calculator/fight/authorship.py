"""What wrote each breakdown row, measured while the fight runs."""

import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any

#: Armed by :func:`recording` and read once per fight, when its breakdown is
#: built.  A fight started outside a recording block pays nothing: it gets a
#: plain ``dict`` with no ``__setitem__`` of its own.
_RECORDING: ContextVar[bool] = ContextVar("fight_step_recording", default=False)

#: A step is spelled the way ``trigger_stream.MechanicCapability.impl`` spells
#: a pricing home, so the two can be compared without either being rewritten.
_PACKAGE_PREFIX = "src.calculator."

#: The answer for a fight nobody recorded.
_NO_STEPS: Mapping[str, str] = MappingProxyType({})


def _writing_step() -> str:
    """The module and outermost function of the frame writing a row."""
    # The caller's caller is the frame that wrote the row.
    # pylint: disable=protected-access
    frame = sys._getframe(2)  # noqa: SLF001 - the writer of the row being stored
    module = str(frame.f_globals["__name__"])
    function = frame.f_code.co_qualname.split(".<locals>.")[0]
    return f"{module.removeprefix(_PACKAGE_PREFIX)}.{function}"


class RecordedBreakdown(dict):
    """A breakdown that remembers which step wrote each of its rows."""

    def __init__(self) -> None:
        """Start empty, beside an empty side table."""
        super().__init__()
        self.steps: dict[str, str] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        """Record the writing step, then store the row."""
        self.steps[str(key)] = _writing_step()
        super().__setitem__(key, value)


def new_breakdown() -> dict[str, Any]:
    """A recording breakdown while tracing is armed, else a plain one."""
    return RecordedBreakdown() if _RECORDING.get() else {}


def steps_of(breakdown: Mapping[str, Any]) -> Mapping[str, str]:
    """The measured step per row key, empty for a fight nobody recorded."""
    return getattr(breakdown, "steps", _NO_STEPS)


@contextmanager
def recording() -> Iterator[None]:
    """Arm step recording for every fight started inside the block."""
    token = _RECORDING.set(True)
    try:
        yield
    finally:
        _RECORDING.reset(token)
