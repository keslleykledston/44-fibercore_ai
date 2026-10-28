"""Read-your-writes: a 2xx must only reach the client AFTER the transaction committed.

FastAPI runs the exit code of a yield dependency AFTER the response is sent unless the dependency has scope="function". A client
that fires its next call as soon as it has the 201 would otherwise race the commit (seen as "job not found" right after a preview).
"""
from fastapi.routing import APIRoute

from app.api.deps import tenant_conn
from app.main import app


def _walk(dep):
    yield dep
    for sub in dep.dependencies:
        yield from _walk(sub)


def _api_routes(routes):
    for r in routes:
        if isinstance(r, APIRoute):
            yield r
        elif hasattr(r, "original_router"):  # FastAPI >= 0.12x wraps included routers lazily
            yield from _api_routes(r.original_router.routes)


def test_every_route_commits_before_the_response_is_sent():
    seen = 0
    for route in _api_routes(app.routes):
        for dep in _walk(route.dependant):
            if dep.call is tenant_conn:
                seen += 1
                assert dep.scope == "function", f"{route.path} {sorted(route.methods)} commits after the response"
    assert seen > 20  # guards the guard: the walk really found the tenant routes
