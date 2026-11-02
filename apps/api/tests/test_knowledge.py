"""Knowledge base (ADR-0041, PR5): reference data only. Nothing reaches an OLT, nothing is executable, a broken base is refused whole."""
import copy
import json

import pytest
from sqlalchemy import text

from app.core import knowledge
from tests.conftest import hdr

FEATURE = "fleet_manager"


@pytest.fixture(autouse=True)
def _cleanup(migrated):
    yield
    with migrated.begin() as c:
        c.execute(text("DELETE FROM tenant_features WHERE feature = 'fleet_manager'"))


def _on(migrated, tenant):
    with migrated.begin() as c:
        c.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
        c.execute(text("INSERT INTO tenant_features (tenant_id, feature, enabled) VALUES (:t,:f,true) ON CONFLICT (tenant_id, feature) DO UPDATE SET enabled = true"), {"t": tenant, "f": FEATURE})


def _parts():
    d = knowledge.DATA
    j = lambda n: json.loads((d / n).read_text(encoding="utf-8"))  # noqa: E731
    return j("sources.json"), j("commands.json"), j("recipes.json"), j("matrix.json"), j("intents.json"), {p.stem: p.read_text(encoding="utf-8") for p in (d / "runbooks").glob("*.md")}


def test_the_shipped_base_is_valid_and_nothing_in_it_is_executable():
    b = knowledge.load()
    assert len(b["sources"]["items"]) == 25 and len(b["commands"]["items"]) == 19 and len(b["runbooks"]["items"]) == 8
    assert all(c["executable"] is False and c["verification"] == "not_tested_in_fibercore" for c in b["commands"]["items"])
    assert all(r["status"] != "homologated" for r in b["recipes"]["items"]) and b["recipes"]["deny_apply_by_default"] is True
    assert all(m["profile_apply"] == "blocked_by_default" for m in b["homologation"]["matrix"])
    assert "rendered_commands" not in json.dumps(b)                                      # no ready-to-run sequence rides along


@pytest.mark.parametrize("mutate,why", [
    (lambda s, c, r, m, i, rb: c["commands"][0].update(can_execute_on_device=True), "executable"),
    (lambda s, c, r, m, i, rb: c["commands"][0].update(syntax="config terminal"), "start with display/show/cd"),
    (lambda s, c, r, m, i, rb: c["commands"][0].update(syntax="display ont info then commit"), "write word"),
    (lambda s, c, r, m, i, rb: c["commands"][0].update(source_ids=["NOPE-99"]), "unknown source"),
    (lambda s, c, r, m, i, rb: c["commands"][0].update(verification="verified_on_device"), "verification"),
    (lambda s, c, r, m, i, rb: c.update(execution_default="allow"), "deny"),
    (lambda s, c, r, m, i, rb: s["sources"][0].update(url="http://example.test/x"), "https"),
    (lambda s, c, r, m, i, rb: r.update(deny_apply_by_default=False), "deny_apply"),
    (lambda s, c, r, m, i, rb: r["recipes"][0].update(status="homologated"), "status"),
    (lambda s, c, r, m, i, rb: m["matrix"][0].update(profile_apply="allowed"), "apply"),
    (lambda s, c, r, m, i, rb: i.update(state="ready"), "design_only"),
    (lambda s, c, r, m, i, rb: r["recipes"][0]["examples"].append("commit"), "recipe example is a write"),
    (lambda s, c, r, m, i, rb: r["recipes"][0]["examples"].append("show running; reboot"), "recipe example chains a write"),
    (lambda s, c, r, m, i, rb: r["recipes"][0]["steps"].append("then run `commit` on the OLT"), "recipe step shows a write command"),
    (lambda s, c, r, m, i, rb: rb.update(huawei=rb["huawei"] + "\nRun `save` now.\n"), "runbook shows a write command"),
    (lambda s, c, r, m, i, rb: rb.update(huawei=rb["huawei"] + "\nUse `display ont info then reboot`.\n"), "runbook command carries a write word"),
    (lambda s, c, r, m, i, rb: rb.update(huawei=rb["huawei"] + "\nAsk the operator to `operator reboot`.\n"), "write word behind a non-command first token"),
    (lambda s, c, r, m, i, rb: r["recipes"][0]["restrictions"].append("never `x; save`"), "write word in a restriction span"),
])
def test_any_broken_invariant_refuses_the_whole_base(mutate, why):
    s, c, r, m, i, rb = copy.deepcopy(_parts())
    mutate(s, c, r, m, i, rb)
    with pytest.raises(knowledge.KnowledgeInvalid):
        knowledge.validate(s, c, r, m, i, rb, (knowledge.DATA / "playbook.md").read_text(encoding="utf-8"))


def test_a_write_command_in_the_playbook_refuses_the_base():
    s, c, r, m, i, rb = copy.deepcopy(_parts())
    with pytest.raises(knowledge.KnowledgeInvalid):
        knowledge.validate(s, c, r, m, i, rb, "Passo: execute `reload` no equipamento.")


def test_recipes_serve_only_read_check_preview_steps_and_count_the_change_steps_left_out():
    b = knowledge.load()
    for r in b["recipes"]["items"]:
        assert r["steps"] and all(x.split()[0].lower() in knowledge.SAFE_STEP_OPENERS for x in r["steps"])
    by = {r["vendor"]: r for r in b["recipes"]["items"]}
    assert by["datacom"]["omitted_change_steps"] == 3 and by["huawei"]["omitted_change_steps"] == 3 and "Save and verify through existing executor" not in str(b["recipes"])
    words = {w for r in b["recipes"]["items"] for x in r["steps"] for w in knowledge._words(x)}
    assert not (words & knowledge.PROSE_BLOCK)
    # a step that is not an allowlisted opener is never served, whatever it says
    served, omitted = knowledge.served_steps({"steps": ["Preview the graph", "Reconfigure the PON quietly", "Check the ONU"]})
    assert served == ["Preview the graph", "Check the ONU"] and omitted == 1
    for bad in ("Check the VLAN, then configure the service", "Check the PON and set the VLAN", "Verify it and enable the port", "Read the card, then disable it", "Inspect it and copy the file"):
        assert knowledge.served_steps({"steps": [bad]}) == ([], 1), bad   # a safe opening verb does not make the rest of the step safe


def test_the_shipped_recipes_show_only_read_commands_and_prose_may_still_warn_about_writes():
    b = knowledge.load()
    ex = [e for r in b["recipes"]["items"] for e in r["examples"]]
    assert ex and all(e.split()[0] in knowledge.READ_FIRST_TOKENS for e in ex)
    assert "intelbras" in [r["vendor"] for r in b["recipes"]["items"]] and "deploy profile line" not in str(b["recipes"])


def test_flag_roles_and_content(client, seed, inv, migrated):
    h, hn1 = hdr(client, "alice", seed, "A"), hdr(client, "dave", seed, "A")
    r = client.get("/v1/knowledge", headers=h)
    assert r.status_code == 403 and r.json()["detail"] == "feature_disabled"
    _on(migrated, seed["A"])
    assert client.get("/v1/knowledge", headers=hn1).status_code == 403                    # noc_n1 holds no fleet:read
    assert client.get("/v1/knowledge", headers=h).json()["sections"] == {"sources": 25, "commands": 19, "runbooks": 8, "intents": 6, "recipes": 8, "homologation": 8}
    cmds = client.get("/v1/knowledge/commands", headers=h).json()
    assert cmds["items"] and all(c["executable"] is False for c in cmds["items"]) and "can_execute_on_device" not in json.dumps(cmds)
    assert client.get("/v1/knowledge/nope", headers=h).status_code == 404
    assert client.get("/v1/knowledge/runbooks", headers=h).json()["items"][0]["text"]
    assert client.get("/v1/knowledge").status_code in (401, 403)                          # no token


def test_a_broken_base_answers_503_not_a_partial_page(client, seed, inv, migrated, monkeypatch):
    _on(migrated, seed["A"])
    h = hdr(client, "alice", seed, "A")

    def boom():
        raise knowledge.KnowledgeInvalid("x")
    monkeypatch.setattr(knowledge, "load", boom)
    r = client.get("/v1/knowledge/commands", headers=h)
    assert r.status_code == 503 and r.json()["detail"] == "knowledge_base_invalid"
