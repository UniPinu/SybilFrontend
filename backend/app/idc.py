"""One lazily-created IDCClient, shared by the scripts and the API.

Instantiating IDCClient opens the packaged DuckDB index (~80 MB on disk, shipped
inside idc-index-data), so it is worth doing exactly once per process.
"""
from __future__ import annotations

import functools
import logging

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def get_client():
    from idc_index import IDCClient

    log.info("opening IDC index")
    return IDCClient()


@functools.lru_cache(maxsize=1)
def get_clinical_client():
    """Client with the NLST clinical tables fetched (one-time download)."""
    client = get_client()
    client.fetch_index("clinical_index")
    return client
