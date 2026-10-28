"""GenieACS NBI READ-ONLY client example; run only inside permitted private Edge.

NEVER expose it as arbitrary URL proxy. API keys, auth and allowlists belong to Edge.
"""
from __future__ import annotations

from typing import Any

import httpx


class GenieACSReadOnlyClient:
    def __init__(self, base_url: str, http_client: httpx.AsyncClient):
        # URL MUST be supplied from a vetted local Edge config, not an untrusted HTTP request.
        self._base_url = base_url.rstrip("/")
        self._client = http_client

    async def get_devices(self, projection: str = "_id,_lastInform,_deviceId", query: dict | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {"projection": projection}
        if query:
            import json
            params["query"] = json.dumps(query, separators=(",", ":"))
        response = await self._client.get(f"{self._base_url}/devices", params=params, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Expected GenieACS devices list")
        return data
