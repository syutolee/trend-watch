import random
import time
from typing import Any

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from trend_watch.utils.logging import get_logger

log = get_logger(__name__)


def build_session(max_retries: int = 3, backoff_factor: float = 0.5) -> Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def polite_get(
    session: Session,
    url: str,
    *,
    min_delay: float = 1.0,
    max_delay: float = 3.0,
    timeout: int = 30,
    **kwargs: Any,
) -> Response:
    delay = random.uniform(min_delay, max_delay)
    log.debug("Sleeping %.2fs before GET %s", delay, url)
    time.sleep(delay)
    response = session.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response
