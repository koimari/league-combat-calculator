"""The process-global state a test borrows, and the check that it gave it back.

``src.app`` is imported once per xdist worker and every test on that worker
shares its module namespace and its Flask config, so a test that rebinds
``calculate_payload`` or writes ``app.config[...]`` without a restore decides
those for every test that lands after it.  That is why issue #263's failures
were whole-file cascades in files the diff never touched, green serially and
green on rerun: the leak and its victim only ever meet under ``-n auto``.

``WATCHED_MODULES`` is the table; every attribute under a watched module is
derived from ``vars()``, so a new global cannot be forgotten.  Two module
singletons are deliberately outside it.  ``src.db``'s ``_engine`` is created
by any route that touches the database, so a bound engine is the app working
rather than a test leaking.  ``data_registry._DATA_VERSION`` is a monotonic
counter whose bump is what ``write_runtime_cache`` promises.

A value counts as given back when it is equal, not only when it is the same
object: ``db.reset()`` rebinds ``_redis_state`` to a fresh empty dict, and
that is a restore.

This is a test helper, not a test module: it holds no assertions.
"""

import sys

#: Module namespaces whose bindings a test must give back.
WATCHED_MODULES = ("src.app",)


class _Absent:
    """Stands for a key the mapping does not hold, and says so in a report."""

    def __repr__(self) -> str:
        return "<absent>"


_ABSENT = _Absent()


def _surfaces():
    """``(label, mapping)`` for each watched namespace that is imported.

    The label is a format template with one field for the key, so a report
    names a leak the way source would write it: ``src.app.calculate_payload``
    for a module attribute and ``src.app.app.config['TESTING']`` for a
    config key.
    """
    for name in WATCHED_MODULES:
        module = sys.modules.get(name)
        if module is not None:
            yield name + ".{}", module.__dict__
    app = sys.modules.get("src.app")
    if app is not None:
        yield "src.app.app.config[{!r}]", app.app.config


def snapshot() -> dict[str, dict]:
    """A shallow copy of every watched mapping, keyed by its label."""
    return {label: dict(mapping) for label, mapping in _surfaces()}


def _changed(before: dict, mapping) -> list[str]:
    """Keys of *mapping* whose value differs from what *before* recorded."""
    return [
        key
        for key in before.keys() | mapping.keys()
        if not _same(before.get(key, _ABSENT), mapping.get(key, _ABSENT))
    ]


def _same(was, now) -> bool:
    """Whether *now* is the value *was*, by identity or by equality.

    Equality is tried second and its failure is a difference: a value whose
    ``__eq__`` raises cannot claim to be the one that was there.
    """
    if was is now:
        return True
    try:
        return bool(was == now)
    except Exception:  # noqa: BLE001 - an unanswerable == is a difference
        return False


def restore_and_report(before: dict[str, dict]) -> list[str]:
    """Put every changed key back, and name the ones that had moved."""
    report = []
    for label, mapping in _surfaces():
        was = before.get(label)
        if was is None:
            continue
        for key in _changed(was, mapping):
            report.append(
                f"{label.format(key)}: "
                f"{was.get(key, _ABSENT)!r} -> {mapping.get(key, _ABSENT)!r}"
            )
            if key in was:
                mapping[key] = was[key]
            else:
                del mapping[key]
    return sorted(report)
