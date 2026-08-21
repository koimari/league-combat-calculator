"""Hash a tracked file the way its receipts were written: as committed.

``data/atoms/manifest.json`` records a ``source_ref`` whose short hash is the
sha256 of the cached source file.  The atomizer writes that hash from the
bytes git stores, which are LF; this repo checks out with ``core.autocrlf``,
so on Windows the same file is CRLF on disk and hashes to something else.  A
test that hashed the working copy would pass on Linux and fail on Windows for
a manifest that is correct on both.

So the line endings are normalised before hashing.  This is not a Windows
special case bolted onto a Linux answer: the question the receipt asks is
"what content did this receipt come from", and content is what survives the
checkout filter.

This is a test helper, not a test module: it holds no assertions.
"""

import hashlib
from pathlib import Path


def sha256_as_committed(path: Path | str) -> str:
    """The sha256 of *path* with CRLF newlines normalised back to LF."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
