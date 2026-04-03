"""Shared requests session with retries (urllib3)."""
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from config import (
    HTTP_RETRY_BACKOFF,
    HTTP_RETRY_TOTAL,
    HTTP_STATUS_FORCELIST,
    REQUEST_CONNECT_TIMEOUT,
    REQUEST_READ_TIMEOUT,
)


def make_http_session() -> Session:
    s = Session()
    retries = Retry(
        total=HTTP_RETRY_TOTAL,
        backoff_factor=HTTP_RETRY_BACKOFF,
        status_forcelist=HTTP_STATUS_FORCELIST,
        allowed_methods=frozenset(["GET", "POST", "HEAD"]),
    )
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


def request_timeout() -> tuple:
    return REQUEST_CONNECT_TIMEOUT, REQUEST_READ_TIMEOUT
