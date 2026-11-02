"""Knowledge base (ADR-0041, PR5): documented sources, read-only command syntax, runbooks, service intents and translation recipes of the OLT vendors.

It is REFERENCE DATA, never an executor and never proof of support: a command listed here is `documented`, not `verified_on_device`, and nothing in this module can reach an OLT. The files ship
inside the image (`app/knowledge_data`) and are checked on load; if any invariant fails the whole base is refused (`KnowledgeInvalid`), so a bad edit shows as an error, not as a quietly wrong page.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "knowledge_data"
SECTIONS = ("sources", "commands", "runbooks", "intents", "recipes", "homologation")
READ_FIRST_TOKENS = frozenset({"display", "show", "cd"})   # `cd` only changes the CLI mode; it is documented as "not a query by itself"
WRITE_WORDS = frozenset({"set", "config", "configure", "commit", "add", "del", "delete", "undo", "save", "reboot", "reset", "shutdown", "write", "copy", "erase", "format", "load", "upgrade",
                         "no", "clear", "create", "modify", "deploy", "apply", "enable", "disable", "activate", "reload", "restart"})
RECIPE_STATUS = frozenset({"documented_example_not_homologated", "research_only", "inherited_in_fibercore_verify_local"})
VENDOR_RE = re.compile(r"^[a-z0-9-]{2,30}$")
SAFE_STEP_OPENERS = frozenset({"check", "read", "preview", "validate", "verify", "inspect", "select", "acquire", "record"})   # an allowlist: a step opens with one of these or it is not served
PROSE_BLOCK = WRITE_WORDS - {"config"}   # every change verb we know, in prose too; only "config" is let through because the vendors use it as a NOUN ("Run/Config/Match")
CODE_SPAN_RE = re.compile(r"`([^`\n]{1,200})`")


class KnowledgeInvalid(Exception):
    """The shipped knowledge base broke one of its safety invariants."""


def _json(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _need(ok: bool, why: str) -> None:
    if not ok:
        raise KnowledgeInvalid(why)


def _words(syntax: str) -> list[str]:
    return [w for w in re.split(r"[^a-z_]+", syntax.lower()) if w]


def _check_code(text_: str, where: str) -> None:
    """Prose may SAY "commit" (a runbook warns against it); a `code span` may not carry a write word anywhere in it, whatever its first token."""
    for span in CODE_SPAN_RE.findall(text_):
        w = _words(span)
        _need(not (set(w) & WRITE_WORDS), f"{where}: a write word is shown as code: {span[:40]}")   # anywhere in the span, whatever its first token


def served_steps(recipe: dict) -> tuple[list[str], int]:
    """The steps of a recipe the base shows (reading, checking, previewing, documenting) and how many CHANGE steps were left out. Fail-closed: only an allowlisted opening verb is served."""
    shown = [x for x in recipe["steps"] if (_words(x) or [""])[0] in SAFE_STEP_OPENERS and not (set(_words(x)) & PROSE_BLOCK)]   # prose may say "Config" as a noun; it may not say a change verb
    return shown, len(recipe["steps"]) - len(shown)


def validate(sources: dict, commands: dict, recipes: dict, matrix: dict, intents: dict, runbooks: dict[str, str], playbook: str = "") -> None:
    ids = [s["id"] for s in sources["sources"]]
    _need(len(ids) == len(set(ids)) and ids, "sources: ids must be unique and not empty")
    for s in sources["sources"]:
        _need(str(s["url"]).startswith("https://") and " " not in s["url"], f"sources: {s['id']} must link by https")
    known = set(ids)
    _need(commands.get("execution_default") == "deny", "commands: execution_default must be 'deny'")
    seen = set()
    for c in commands["commands"]:
        cid = c["id"]
        _need(cid not in seen, f"commands: duplicate id {cid}")
        seen.add(cid)
        _need(c["can_execute_on_device"] is False, f"commands: {cid} may not be executable")
        _need(c["verification"] == "not_tested_in_fibercore", f"commands: {cid} claims a verification this base cannot prove")
        _need(bool(c["source_ids"]) and set(c["source_ids"]) <= known, f"commands: {cid} cites an unknown source")
        _need(bool(VENDOR_RE.match(c["vendor"])), f"commands: {cid} has a bad vendor")
        words = _words(c["syntax"])
        _need(bool(words) and words[0] in READ_FIRST_TOKENS, f"commands: {cid} must start with display/show/cd")
        _need(not (set(words) & WRITE_WORDS), f"commands: {cid} carries a write word")
    _need(recipes.get("deny_apply_by_default") is True, "recipes: deny_apply_by_default must be true")
    for r in recipes["recipes"]:
        _need(r["status"] in RECIPE_STATUS, f"recipes: {r['vendor']} has an unknown status")
        _need(set(r["source_ids"]) <= known, f"recipes: {r['vendor']} cites an unknown source")
        for ex in r["examples"]:   # every example shown to the reader is itself a read-only command
            w = _words(ex)
            _need(bool(w) and w[0] in READ_FIRST_TOKENS and not (set(w) & WRITE_WORDS), f"recipes: {r['vendor']} example is not a read-only command: {ex[:40]}")
        _need(bool(served_steps(r)[0]), f"recipes: {r['vendor']} has no step that is safe to show")
        for field in ("steps", "restrictions"):
            for line in r[field]:
                _check_code(line, f"recipes: {r['vendor']} {field}")
    for row in matrix["matrix"]:
        _need(row["profile_apply"] == "blocked_by_default", f"matrix: {row['vendor']} may not allow apply")
        _need(row["evidence"] == "none" or row["evidence"], f"matrix: {row['vendor']} needs an evidence field")
    _need(intents.get("state") == "design_only", "intents: state must be design_only")
    _need(len(runbooks) > 0 and all(t.strip() for t in runbooks.values()), "runbooks: empty")
    for vendor, body in runbooks.items():
        _check_code(body, f"runbooks: {vendor}")
    _check_code(playbook, "homologation playbook")


@lru_cache(maxsize=1)
def load() -> dict:
    """The validated base, keyed by section. Cached: the files are part of the image."""
    sources, commands, recipes, matrix, intents = (_json(f) for f in ("sources.json", "commands.json", "recipes.json", "matrix.json", "intents.json"))
    runbooks = {p.stem: p.read_text(encoding="utf-8") for p in sorted((DATA / "runbooks").glob("*.md"))}
    playbook = (DATA / "playbook.md").read_text(encoding="utf-8")
    validate(sources, commands, recipes, matrix, intents, runbooks, playbook)
    return {
        "sources": {"status": sources["status"], "license_policy": sources["license_policy"], "items": sources["sources"]},
        "commands": {"warning": commands["warning"], "items": [{**{k: c[k] for k in ("id", "vendor", "family", "syntax", "cli_context", "purpose", "source_ids", "confidence", "verification", "risk", "notes")},
                                                                "executable": False} for c in commands["commands"]]},
        "runbooks": {"items": [{"vendor": v, "text": t} for v, t in runbooks.items()]},
        "intents": {"state": intents["state"], "note": intents["note"], "items": intents["service_intents"]},
        "recipes": {"deny_apply_by_default": True,
                    "items": [{**{k: r[k] for k in ("vendor", "family", "source_ids", "status", "examples", "restrictions")}, "steps": served_steps(r)[0], "omitted_change_steps": served_steps(r)[1]}
                              for r in recipes["recipes"]]},
        "homologation": {"status": matrix["status"], "matrix": matrix["matrix"], "playbook": playbook},
    }
