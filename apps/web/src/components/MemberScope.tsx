"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { MfaStepUp } from "@/components/MfaStepUp";
import { SCOPE_EXPLAIN, canSaveScope, toggle } from "@/lib/orgSecurity";
import { TEAM_ERROR } from "@/lib/team";
import type { MemberScope as Scope } from "@/lib/types";

/** Escopo por site/OLT de UMA pessoa (ADR-0049 D2): quem tem escopo só lê a rede dentro dele. As opções vêm da API ao abrir. */
export function MemberScope({ userId, name }: { userId: string; name: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);
  const [data, setData] = useState<Scope | null>(null);
  const [pops, setPops] = useState<string[]>([]);
  const [olts, setOlts] = useState<string[]>([]);
  const retry = useRef<(() => Promise<void>) | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  async function load() {
    setError(null);
    try {
      const res = await fetch(`/bff/team/members/${userId}/scope`, { cache: "no-store" });
      const j = (await res.json().catch(() => ({}))) as Scope & { error?: string };
      if (!res.ok) { setError(TEAM_ERROR[j.error ?? "failed"] ?? TEAM_ERROR.failed); return; }
      setData(j); setPops(j.pop_ids); setOlts(j.olt_ids);
    } catch { setError(TEAM_ERROR.failed); }
  }
  const openIt = () => { setOpen(true); setData(null); void load(); };
  const close = () => { setOpen(false); setNeedStepUp(false); setError(null); trigger.current?.focus(); };

  async function call(method: "PUT" | "DELETE", body?: unknown) {
    retry.current = () => call(method, body); setBusy(true); setError(null);
    try {
      const res = await fetch(`/bff/team/members/${userId}/scope`, { method, headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify(body ?? {}) });
      const j = (await res.json().catch(() => ({}))) as { error?: string };
      if (res.ok) { setNeedStepUp(false); close(); router.refresh(); return; }
      if (j.error === "mfa_recent_required") { setNeedStepUp(true); return; }
      setError(TEAM_ERROR[j.error ?? "failed"] ?? TEAM_ERROR.failed);
    } catch { setError(TEAM_ERROR.failed); } finally { setBusy(false); }
  }

  const check = "flex min-h-touch items-center gap-2";
  return (
    <>
      <button ref={trigger} type="button" onClick={openIt} aria-haspopup="dialog" data-testid="scope-open" aria-label={`Escopo de ${name}`}
        className="min-h-touch rounded-btn border border-line px-3 text-sm hover:bg-bg">Escopo</button>
      <EntityDetailDrawer open={open} onClose={close} title={`Escopo de ${name}`}>
        <div className="grid gap-4 text-sm" data-testid="scope-panel">
          <p className="text-muted">{SCOPE_EXPLAIN}</p>
          {error && <p role="alert" data-testid="scope-error" className="text-danger">{error}</p>}
          {needStepUp && <MfaStepUp onDone={() => retry.current && void retry.current()} />}
          {data === null ? (!error && <p role="status">Carregando…</p>) : !data.scopable ? (
            <p data-testid="scope-not-scopable">Esta função precisa ver o provedor inteiro. Só Engenheiro, Operador NOC e Atendimento aceitam escopo.</p>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); void call("PUT", { pop_ids: pops, olt_ids: olts }); }} className="grid gap-4" data-testid="scope-form">
              <fieldset className="grid gap-1">
                <legend className="mb-1 font-medium">Sites</legend>
                {data.options.pops.length === 0 ? <p className="text-muted">Nenhum site cadastrado.</p> : data.options.pops.map((p) => (
                  <label key={p.id} className={check}><input type="checkbox" className="size-4" checked={pops.includes(p.id)} onChange={(e) => setPops(toggle(pops, p.id, e.target.checked))} />{p.name}</label>
                ))}
                <p className="text-xs text-muted">Um site inclui todas as OLTs dele, também as que forem cadastradas depois.</p>
              </fieldset>
              <fieldset className="grid gap-1">
                <legend className="mb-1 font-medium">OLTs</legend>
                {data.options.olts.length === 0 ? <p className="text-muted">Nenhuma OLT cadastrada.</p> : data.options.olts.map((o) => (
                  <label key={o.id} className={check}><input type="checkbox" className="size-4" checked={olts.includes(o.id)} onChange={(e) => setOlts(toggle(olts, o.id, e.target.checked))} />{o.name}</label>
                ))}
              </fieldset>
              <button type="submit" disabled={busy || !canSaveScope(pops, olts)} data-testid="scope-save"
                className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">Salvar escopo</button>
              {data.restricted && (
                <button type="button" disabled={busy} onClick={() => void call("DELETE")} data-testid="scope-clear"
                  className="min-h-touch rounded-btn border border-line px-4 hover:bg-bg disabled:opacity-60">Remover restrição (provedor inteiro)</button>
              )}
            </form>
          )}
        </div>
      </EntityDetailDrawer>
    </>
  );
}
