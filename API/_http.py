"""Shared request handling for both providers."""

import logging

import requests

logger = logging.getLogger(__name__)


class APIError(RuntimeError):
    """The provider could not return the requested JSON."""


def get_json(session: requests.Session, url: str, params: dict) -> dict | list:
    """Fetch JSON with a timeout and report failures without exposing credentials."""
    secrets = ("api_key", "apikey")
    debug_params = {name: value for name, value in params.items() if name not in secrets}
    logger.debug("GET %s %s", url, debug_params)

    try:
        response = session.get(url, params=params, timeout=30)
    except requests.RequestException as error:
        raise APIError(f"GET {url} failed ({type(error).__name__})") from None

    try:
        payload = response.json()
    except ValueError:
        payload = None

    error = payload.get("error") if isinstance(payload, dict) else None
    if not response.ok or error:
        detail = response.reason
        if isinstance(payload, dict):
            detail = payload.get("reason") or payload.get("description") or error or detail
        message = str(detail)
        for name in secrets:
            if params.get(name):
                message = message.replace(str(params[name]), "[redacted]")
        raise APIError(f"GET {url} returned HTTP {response.status_code}: {message[:300]}")

    if not isinstance(payload, (dict, list)):
        raise APIError(f"GET {url} returned HTTP {response.status_code} with no JSON object or array")
    return payload
