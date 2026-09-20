"""The calculator package. Import from the owning module, not from here.

The package re-exports nothing. Its one job at import time is publishing the
rune compiler tables that `rune_effects` reads.
"""

from .rune_paths import publish_rune_compilers

publish_rune_compilers()
