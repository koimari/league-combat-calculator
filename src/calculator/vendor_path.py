"""The vendored lolstaticdata checkout: on the import path, and imported here.

``vendor/lolstaticdata`` is a checkout rather than an installed package, so a
reader reaches it through this leaf.  Putting the root on ``sys.path`` and
performing the import in one module is what lets a caller state the dependency
as an import instead of as an ordering it has to remember.
"""

import importlib
import sys
from pathlib import Path

#: The checkout root, and where its generators write their output.
LOLSTATICDATA_ROOT = (
    Path(__file__).resolve().parent.parent.parent / "vendor" / "lolstaticdata"
)
if str(LOLSTATICDATA_ROOT) not in sys.path:
    sys.path.insert(0, str(LOLSTATICDATA_ROOT))

lsd_utils = importlib.import_module("lolstaticdata.common.utils")
download_json = lsd_utils.download_json
get_latest_patch_version = lsd_utils.get_latest_patch_version

__all__ = [
    "LOLSTATICDATA_ROOT",
    "download_json",
    "get_latest_patch_version",
    "lsd_utils",
]
