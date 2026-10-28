import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import make_engine, scoped_connection
from tests.conftest import agent, hdr, login, snap

CSV_HDR = "erp_customer_id,display_name,document,contract_status,onu_serial\n"


def post_csv(client, headers, body, source="csv-test"):
    return client.post(f"/v1/erp/import-csv?source={source}", headers={**headers, "content-type": "text/csv"}, content=body)


@pytest.fixture(scope="module")
def onus_ready(seed, inv, migrated):
    """Tenant A has ONUs HWTC-ERP-1 (OLT-E1) and a duplicated serial on two OLTs."""
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app)
    a = agent(c, inv, "a1")
    one = snap(inv, name="OLT-E1", onus=[{"serial": "ERP00000001", "status": "online"}, {"serial": "ERP00000002", "status": "online"},
                                         {"serial": "DUP00000001", "status": "online"},
                                         {"serial": "RACE0000001", "status": "online"}])
    two = snap(inv, name="OLT-E2", onus=[{"serial": "DUP00000001", "status": "online"}])
    assert c.post("/v1/edge/olt-snapshots", headers=a, json=one).status_code == 202
    assert c.post("/v1/edge/olt-snapshots", headers=a, json=two).status_code == 202
    return True


def test_import_hashes_document_and_suggests_by_serial(client, seed, onus_ready, migrated):
    h = hdr(client, "alice", seed, "A")
    body = CSV_HDR + "C1,Maria Silva,123.456.789-09,active,ERP00000001\nC2,Joao Souza,,suspended,\n"
    r = post_csv(client, h, body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["accepted"], j["rejected_count"], j["suggestions"], j["conflicts"]) == (2, 0, 1, 0)
    with migrated.connect() as c:
        row = c.execute(text("SELECT document_hmac, document_last4 FROM customers WHERE erp_customer_id='C1' AND tenant_id=:t"),
                        {"t": seed["A"]}).one()
        dump = " ".join(str(v) for r2 in c.execute(text("SELECT * FROM customers WHERE tenant_id=:t"), {"t": seed["A"]}) for v in r2)
    assert row.document_last4 == "8909" and len(row.document_hmac) == 64
    assert "12345678909" not in dump and "123.456.789-09" not in dump  # plaintext document never stored
    assert row.document_hmac != hashlib.sha256(b"12345678909").hexdigest()  # keyed + tenant scoped, not a bare hash
    sug = client.get("/v1/associations?status=suggested", headers=h).json()
    assert any(a["onu_serial"] == "ERP00000001" and a["score"] == 95 and a["customer_name"] == "Maria Silva" for a in sug)


def test_row_validation_never_echoes_values(client, seed, onus_ready):
    h = hdr(client, "alice", seed, "A")
    body = CSV_HDR + "C3,Bad Doc,123,active,\nC4,,,active,\nC5,Status,,weird,\nC6,Ctrl\x07Name,,active,\nC7,Ok,,active,\n"
    j = post_csv(client, h, body).json()
    assert j["accepted"] == 1 and j["rejected_count"] == 4
    assert "123" not in str(j["rejected"]) and "Bad Doc" not in str(j["rejected"])


def test_csv_structure_limits(client, seed, onus_ready):
    h = hdr(client, "alice", seed, "A")
    assert post_csv(client, h, "foo,bar\n1,2\n").status_code == 422  # unknown columns
    assert post_csv(client, h, CSV_HDR, source="Bad Source!").status_code == 422
    assert post_csv(client, h, "x" * (2 * 1024 * 1024 + 1)).status_code == 413
    r = client.post("/v1/erp/import-csv?source=csv-test", headers={**h, "content-type": "text/csv"},
                    content=iter([b"a,b\n"] * 3))  # chunked upload (no Content-Length)
    assert r.status_code in (411, 413)
    rows = "".join(f"R{i},N{i},,active,\n" for i in range(5001))
    assert post_csv(client, h, CSV_HDR + rows).status_code == 413
    assert post_csv(client, h, CSV_HDR + 'A,"unterminated\n').status_code in (200, 422)  # never 500
    assert post_csv(client, h, CSV_HDR + "A,B\n").json()["rejected_count"] == 1  # wrong column count


def test_permissions_and_tenant_isolation(client, seed, onus_ready):
    ha = hdr(client, "alice", seed, "A")
    post_csv(client, ha, CSV_HDR + "C9,Isolado,,active,ERP00000002\n")
    assert post_csv(client, hdr(client, "dave", seed, "A"), CSV_HDR + "X,Y,,active,\n").status_code == 403  # noc_n1 cannot import
    hb = hdr(client, "bob", seed, "B")
    assert client.get("/v1/customers", headers=hb).json() == []
    assert client.get("/v1/associations", headers=hb).json() == []
    assert client.get("/v1/customers", headers=hdr(client, "dave", seed, "A")).status_code == 403  # noc_n1 no PII list
    assert len(client.get("/v1/customers", headers=ha).json()) >= 1


def test_approve_flow_audited_and_single_approved_per_onu(client, seed, onus_ready):
    ha = hdr(client, "alice", seed, "A")
    post_csv(client, ha, CSV_HDR + "AP1,Cliente Um,,active,ERP00000002\nAP2,Cliente Dois,,active,ERP00000002\n")
    sug = [a for a in client.get("/v1/associations?status=suggested", headers=ha).json() if a["onu_serial"] == "ERP00000002"]
    assert len(sug) >= 2
    first, second = sug[0], sug[1]
    assert client.post(f"/v1/associations/{first['id']}/approve", headers=ha).status_code == 200
    assert client.post(f"/v1/associations/{first['id']}/approve", headers=ha).status_code == 409  # already reviewed
    assert client.post(f"/v1/associations/{second['id']}/approve", headers=ha).status_code == 409  # onu already approved
    assert client.post(f"/v1/associations/{second['id']}/reject", headers=ha).status_code == 200
    actions = [x["action"] for x in client.get("/v1/audit?limit=200", headers=ha).json()]
    assert "association.approved" in actions and "association.rejected" in actions and "erp.import_csv" in actions


def test_conflict_when_new_customer_claims_approved_onu(client, seed, onus_ready):
    ha = hdr(client, "alice", seed, "A")
    post_csv(client, ha, CSV_HDR + "CF1,Dono Original,,active,ERP00000001\n")
    orig = next(a for a in client.get("/v1/associations?status=suggested", headers=ha).json() if a["customer_name"] == "Dono Original")
    assert client.post(f"/v1/associations/{orig['id']}/approve", headers=ha).status_code == 200
    j = post_csv(client, ha, CSV_HDR + "CF2,Intruso,,active,ERP00000001\n").json()
    assert j["conflicts"] == 1
    intr = next(a for a in client.get("/v1/associations?status=suggested", headers=ha).json() if a["customer_name"] == "Intruso")
    assert intr["score"] == 50 and intr["evidence"]["conflicts_with_approved"] is not None


def test_ambiguous_serial_cannot_be_approved(client, seed, onus_ready):
    ha = hdr(client, "alice", seed, "A")
    j = post_csv(client, ha, CSV_HDR + "AM1,Ambiguo,,active,DUP00000001\n").json()
    assert j["conflicts"] == 1
    amb = [a for a in client.get("/v1/associations?status=suggested", headers=ha).json() if a["customer_name"] == "Ambiguo"]
    assert len(amb) == 2 and all(a["evidence"]["ambiguous_serial"] for a in amb)
    assert client.post(f"/v1/associations/{amb[0]['id']}/approve", headers=ha).status_code == 409


def test_reimport_is_idempotent_and_unmatched_reported(client, seed, onus_ready):
    ha = hdr(client, "alice", seed, "A")
    body = CSV_HDR + "ID1,Idem,,active,ERP00000001\nID2,Sem Onu,,active,NOPE00000000\n"
    j1 = post_csv(client, ha, body).json()
    j2 = post_csv(client, ha, body).json()
    assert len(j1["unmatched_rows"]) == len(j2["unmatched_rows"]) == 1
    sug = [a for a in client.get("/v1/associations?status=suggested", headers=ha).json() if a["customer_name"] == "Idem"]
    assert len(sug) == 1


def test_non_reviewer_cannot_approve_and_runtime_cannot_delete(client, seed, onus_ready, app_url):
    ha = hdr(client, "alice", seed, "A")
    post_csv(client, ha, CSV_HDR + "NR1,Sem Permissao,,active,ERP00000001\n")
    sug = next(a for a in client.get("/v1/associations?status=suggested", headers=ha).json() if a["customer_name"] == "Sem Permissao")
    assert client.post(f"/v1/associations/{sug['id']}/approve", headers=hdr(client, "dave", seed, "A")).status_code == 403
    assert client.post(f"/v1/associations/{sug['id']}/approve", headers=hdr(client, "bob", seed, "B")).status_code == 404  # other tenant
    eng = make_engine(app_url)
    for t in ("customers", "associations", "import_batches"):
        with pytest.raises(DBAPIError), scoped_connection(eng, tenant_id=seed["A"]) as c:
            c.execute(text(f"DELETE FROM {t}"))  # noqa: S608
    with pytest.raises(DBAPIError), scoped_connection(eng, tenant_id=seed["A"]) as c:  # cannot rewrite evidence/score
        c.execute(text("UPDATE associations SET score = 100"))


def test_login_helper_import_kept():
    assert callable(login)


def test_concurrent_approvals_of_same_onu_yield_one_winner_no_500(client, seed, onus_ready, migrated):
    import threading
    ha = hdr(client, "alice", seed, "A")
    post_csv(client, ha, CSV_HDR + "RC1,Race Um,,active,RACE0000001\nRC2,Race Dois,,active,RACE0000001\n")
    sug = [a for a in client.get("/v1/associations?status=suggested", headers=ha).json()
           if a["customer_name"] in ("Race Um", "Race Dois")]
    assert len(sug) == 2
    codes = []

    def go(a):
        codes.append(client.post(f"/v1/associations/{a['id']}/approve", headers=ha).status_code)

    ts = [threading.Thread(target=go, args=(a,)) for a in sug]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [200, 409], codes  # exactly one winner, the loser gets a controlled conflict
