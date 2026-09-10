"""The fight engine's source text, for the suites that assert against it."""

from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "src" / "calculator"


def engine_source() -> str:
    """The orchestrator and every step of the `fight/` package, concatenated.

    Sorted on the posix path, so the order is the same on both platforms.  For
    an assertion about ONE step, read that step with `step_source`: a window
    sliced out of this text is bounded by whatever file sorts next.
    """
    steps = sorted((ENGINE / "fight").rglob("*.py"), key=lambda path: path.as_posix())
    return "\n".join(
        path.read_text(encoding="utf-8") for path in [ENGINE / "damage.py", *steps]
    )


def step_source(relative: str) -> str:
    """One step's source, named by its path under `src/calculator/`."""
    return (ENGINE / relative).read_text(encoding="utf-8")
