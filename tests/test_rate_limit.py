"""Cross-worker abuse-control contracts."""

import contextlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

from src.rate_limit import TokenBucketStore


def test_token_bucket_is_shared_across_store_instances(tmp_path) -> None:
    """Two Gunicorn workers must spend from the same global budget."""
    database = tmp_path / "rate-limits.sqlite3"
    first_worker = TokenBucketStore(database)
    second_worker = TokenBucketStore(database)

    assert first_worker.consume(
        "optimize", capacity=2, refill_per_second=1, now=100
    ) == (
        True,
        0.0,
    )
    assert second_worker.consume(
        "optimize", capacity=2, refill_per_second=1, now=100
    ) == (True, 0.0)

    allowed, retry_after = first_worker.consume(
        "optimize", capacity=2, refill_per_second=1, now=100
    )
    assert allowed is False
    assert retry_after == 1.0

    assert second_worker.consume(
        "optimize", capacity=2, refill_per_second=1, now=101
    ) == (True, 0.0)


def test_token_bucket_never_refills_past_capacity(tmp_path) -> None:
    store = TokenBucketStore(tmp_path / "rate-limits.sqlite3")

    assert store.consume("calculate", capacity=1, refill_per_second=10, now=0)[0]
    assert store.consume("calculate", capacity=1, refill_per_second=10, now=100)[0]
    assert (
        store.consume("calculate", capacity=1, refill_per_second=10, now=100)[0]
        is False
    )


def test_two_workers_cannot_spend_the_same_last_token(tmp_path) -> None:
    database = tmp_path / "rate-limits.sqlite3"
    stores = [TokenBucketStore(database), TokenBucketStore(database)]

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda store: store.consume(
                    "optimize", capacity=1, refill_per_second=0.5, now=100.0
                )[0],
                stores,
            )
        )

    assert sorted(results) == [False, True]


def test_token_bucket_rejects_invalid_policy(tmp_path) -> None:
    store = TokenBucketStore(tmp_path / "rate-limits.sqlite3")

    for capacity, refill in ((0, 1), (1, 0), (-1, 1), (1, -1)):
        try:
            store.consume(
                "calculate",
                capacity=capacity,
                refill_per_second=refill,
                now=0,
            )
        except ValueError:
            pass
        else:
            raise AssertionError((capacity, refill))


def test_store_init_survives_a_sibling_worker_holding_the_write_lock(
    tmp_path,
) -> None:
    """A worker must boot while another worker is mid-``consume``.

    Gunicorn workers construct the store at import time against one shared
    file.  The production container died (gunicorn exit 3, "Worker failed
    to boot") because a sibling's ``BEGIN IMMEDIATE`` write lock made the
    booting worker's ``PRAGMA journal_mode=WAL`` raise ``database is
    locked`` instantly — the WAL switch does not consult the busy-timeout
    handler.  Init must instead wait out a short-lived lock like every
    other statement does.
    """
    database = tmp_path / "rate-limits.sqlite3"
    # check_same_thread=False: the release timer fires on another thread.
    sibling = sqlite3.connect(str(database), check_same_thread=False)
    sibling.execute("BEGIN IMMEDIATE")
    releaser = threading.Timer(0.5, sibling.rollback)
    releaser.start()
    try:
        store = TokenBucketStore(database)
    finally:
        releaser.cancel()
        with contextlib.suppress(sqlite3.Error):
            sibling.rollback()
        sibling.close()
    assert store.consume("calculate", capacity=1, refill_per_second=1, now=0)[0]
