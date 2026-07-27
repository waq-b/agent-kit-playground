"""NotificationHelper — best-effort push notifications via a self-hosted ntfy instance."""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_MIN_LENGTH = 1
_MAX_LENGTH = 4096
_TIMEOUT = 5.0


def notify(message: str) -> None:
    if len(message) < _MIN_LENGTH or len(message) > _MAX_LENGTH:
        logger.warning(
            "notify: invalid message length %d (must be %d-%d chars); not sending",
            len(message), _MIN_LENGTH, _MAX_LENGTH,
        )
        return

    ntfy_url = os.environ.get("NTFY_URL")
    if not ntfy_url:
        logger.warning("notify: NTFY_URL not set; not sending")
        return

    try:
        response = httpx.post(ntfy_url, content=message.encode(), timeout=_TIMEOUT)
        response.raise_for_status()
    except Exception as e:
        logger.warning("notify: failed to send notification to %s: %s", ntfy_url, e)
        return
