"""Issue #216: ``decompose_wiki --wiki-db`` supplies the index the packet gate reads.

The gate's whole read is ``build_reviewed_modules._wiki_revisions``, so that
reader is the assertion: a database the builder writes from a stubbed wiki API
must answer it. No test here touches the network.
"""

import httpx
import pytest

import scripts.build_reviewed_modules as brm
from scripts import decompose_wiki


def _stub_wiki_api(batches) -> httpx.Client:
    """Serve the given ``generator=allpages`` pages, one continuation per batch."""
    remaining = list(batches)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {"query": {"pages": remaining.pop(0)}}
        if remaining:
            payload["continue"] = {"gapcontinue": "Next", "continue": "gapcontinue||"}
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _page(pageid: int, title: str, revid: int | None, timestamp: str = "") -> dict:
    page = {"pageid": pageid, "ns": 0, "title": title}
    if revid is not None:
        page["revisions"] = [{"revid": revid, "timestamp": timestamp}]
    return page


def test_the_built_database_answers_the_readers_query(tmp_path, monkeypatch):
    """Two continuations in, two receipts out, read back through the gate's reader."""
    monkeypatch.setattr(decompose_wiki.time, "sleep", lambda _seconds: None)
    db = tmp_path / "league-wiki.sqlite3"
    batches = [
        [_page(7, "Fixture", 123, "2026-01-01T00:00:00Z")],
        [
            _page(8, "Other", 456, "2026-02-02T00:00:00Z"),
            _page(9, "Revisionless", None),
        ],
    ]
    with _stub_wiki_api(batches) as client:
        written = decompose_wiki.build_wiki_db(db, client)

    assert written == 2  # a page with no revision carries no receipt
    assert brm._wiki_revisions(db) == {
        "Fixture": {"revision_id": 123, "revision_timestamp": "2026-01-01T00:00:00Z"},
        "Other": {"revision_id": 456, "revision_timestamp": "2026-02-02T00:00:00Z"},
    }
    assert not db.with_name(db.name + ".building").exists()


def test_a_failed_fetch_leaves_no_database_behind(tmp_path):
    """The gate must never read a half-built index as authoritative."""
    db = tmp_path / "league-wiki.sqlite3"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        decompose_wiki.build_wiki_db(db, client)

    assert not db.exists()
