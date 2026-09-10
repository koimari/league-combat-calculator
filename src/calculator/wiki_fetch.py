"""One HTTP fetch of a wiki page: a finite wait and an explicit HTTP error."""

import requests as _requests

http_get = _requests.get


def download_page(url: str) -> str:
    """Fetch wiki HTML with a finite wait and explicit HTTP error handling."""
    response = http_get(url, timeout=30)
    response.raise_for_status()
    return response.text
