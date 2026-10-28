import asyncio

import httpx

from app.integrations.genieacs_nbi import GenieACSReadOnlyClient


def test_nbi_read_only_projection():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/devices"
        assert request.url.params["projection"] == "_id,_lastInform"
        return httpx.Response(200, json=[{"_id": "lab-device-1"}])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            adapter = GenieACSReadOnlyClient("http://genieacs.local:7557", http_client)
            return await adapter.get_devices(projection="_id,_lastInform")

    assert asyncio.run(run()) == [{"_id": "lab-device-1"}]
