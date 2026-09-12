from __future__ import annotations

import os

import requests

API_URL = os.environ.get("OLIST_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT = 30


class ApiError(RuntimeError):
    pass


def get(path: str, **params) -> dict | list:
    clean = {k: list(v) if isinstance(v, tuple) else v for k, v in params.items()
             if v is not None and v != [] and v != ()}
    try:
        r = requests.get(f"{API_URL}{path}", params=clean, timeout=TIMEOUT)
    except requests.ConnectionError as exc:
        raise ApiError(f"Cannot reach the API at {API_URL}") from exc
    if r.status_code == 404:
        return []
    if not r.ok:
        raise ApiError(f"{path} returned {r.status_code}: {r.text[:200]}")
    return r.json()
