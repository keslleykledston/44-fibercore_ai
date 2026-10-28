"""Mock Edge agent (Python) used for contract tests until the Go Edge exists (Sprint 1).

Behaviours under test: outbound-only heartbeat to the Gateway, NBI access restricted by a LOCAL
allowlist (never taken from cloud requests => no SSRF), read-only GenieACS client.
"""
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from app.integrations.genieacs_nbi import GenieACSReadOnlyClient


class NotAllowed(Exception):
    pass


class MockEdge:
    def __init__(self, *, edge_id: str, tenant_id: str, version: str, token: str, gateway: httpx.Client,
                 nbi_url: str, nbi_client: httpx.AsyncClient, allowlist: set[str]):
        host = urlparse(nbi_url).netloc
        if host not in allowlist:
            raise NotAllowed(f"NBI host {host!r} not in local allowlist")
        self.edge_id, self.tenant_id, self.version = edge_id, tenant_id, version
        self._gw, self._token = gateway, token
        self._nbi = GenieACSReadOnlyClient(nbi_url, nbi_client)

    def heartbeat(self) -> int:
        r = self._gw.post(
            "/v1/edge/heartbeat",
            headers={"Authorization": f"Bearer {self._token}"},
            json={"edge_id": self.edge_id, "tenant_id": self.tenant_id, "version": self.version,
                  "sent_at": datetime.now(UTC).isoformat()},
        )
        return r.status_code

    async def collect_devices(self) -> list[dict]:
        return await self._nbi.get_devices(projection="_id,_lastInform,_deviceId")
