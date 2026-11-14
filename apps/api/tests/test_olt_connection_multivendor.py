"""ADR-0053: the connection test (`olt.connection`) for the vendors without the `olt_query` catalog (Datacom, Intelbras, Huawei MA5800). The result may carry a null patch and
uptime; every other query still needs the Huawei catalog; a Telnet OLT (read by the Edge's own static entry) is testable. Nothing here reaches equipment."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core import olt_query
from tests.conftest import agent, hdr, snap
from tests.test_fleet_connection import _flag, _test
from tests.test_olt_query import _ask, on  # noqa: F401  (fixture: the olt_query flag + Edge channel)


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features WHERE feature = 'fleet_manager'"))
        c.execute(text("DELETE FROM olt_connection_tests"))


def _olt(client, seed, inv, **kw):
    name = f"OLT-M{uuid4().hex[:6]}"
    assert client.post("/v1/edge/olt-snapshots", headers=agent(client, inv, "a1"), json=snap(inv, name=name, **kw)).status_code == 202
    h = hdr(client, "alice", seed, "A")
    return next(o["id"] for o in client.get("/v1/olts", headers=h).json() if o["name"] == name)


def test_the_connection_result_may_have_null_patch_and_uptime_only_for_the_connection_test():
    ok = {"product": "DM4610 HW2", "version": "5.8.0-065", "patch": None, "uptime_seconds": None}
    assert olt_query.check_result("olt.connection", ok)
    assert olt_query.check_result("olt.connection", {**ok, "product": "OLT8820PLUS", "version": "2.112"})
    assert olt_query.check_result("olt.connection", {"product": "MA5800-X7", "version": "R018", "patch": "SPC100", "uptime_seconds": 1234})   # the old shape still holds
    assert not olt_query.check_result("olt.version", ok)                                      # the Huawei read stays strict
    for bad in ({**ok, "extra": 1}, {k: v for k, v in ok.items() if k != "patch"}, {**ok, "product": "DM;4610"}, {**ok, "version": "x\ny"},
                {**ok, "uptime_seconds": -1}, {**ok, "uptime_seconds": True}, {**ok, "patch": 5}, {**ok, "product": ""}):
        assert not olt_query.check_result("olt.connection", bad), bad


def test_datacom_and_a_telnet_olt_can_be_tested_and_everything_else_needs_the_huawei_catalog(client, seed, inv, on, migrated):  # noqa: F811
    _flag(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    dm = _olt(client, seed, inv, vendor="datacom", model="DM4610 HW2", firmware="5.8.0-065")
    ib = _olt(client, seed, inv, vendor="intelbras", model="OLT8820PLUS", firmware="2.112")
    with migrated.begin() as c:   # registered as Telnet in the cloud: the Edge reads it through its own static entry
        c.execute(text("UPDATE olts SET mgmt_protocol = 'telnet' WHERE id = :i"), {"i": ib})
    for o in (dm, ib):
        r = _test(client, h, o)
        assert r.status_code == 200 and r.json()["outcome"] == "submitted", r.text
    r = _ask(client, h, dm, "olt.board")
    assert r.status_code == 422 and r.json()["detail"] == "vendor_not_supported"
    assert _ask(client, h, ib, "olt.version").status_code == 422
    hw = _olt(client, seed, inv)   # the Huawei default of the fixtures keeps the catalog
    assert _ask(client, h, hw, "olt.board").status_code != 422


def test_ma5800_answers_the_connection_test_and_the_autofind_list_and_nothing_else_of_the_catalog(client, seed, inv, on, migrated):  # noqa: F811
    _flag(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")
    ma = _olt(client, seed, inv, vendor="huawei", model="MA5800-X2", firmware="MA5800V100R024C11")
    assert _test(client, h, ma).status_code == 200
    assert _ask(client, h, ma, "olt.autofind").status_code != 422
    for q in ("olt.board", "olt.version", "olt.time", "olt.profile.line"):
        r = _ask(client, h, ma, q)
        assert r.status_code == 422 and r.json()["detail"] == "vendor_not_supported", q
    dm = _olt(client, seed, inv, vendor="datacom", model="DM4610 HW2", firmware="5.8.0-065")
    assert _ask(client, h, dm, "olt.autofind").status_code == 422   # no driver reads the waiting list on Datacom yet
