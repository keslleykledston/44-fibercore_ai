"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { ACTION_BLOCKED, ACTION_ERROR, ACTION_UNAVAILABLE } from "@/lib/devices";
import type { CpeAction } from "@/lib/types";

type Result = { kind: "submitted" | "blocked"; reason: string | null; jobId: string | null };

/** Uma ação do CPE: pedir cria um pedido de operação (nada é executado aqui); a aprovação e a execução seguem em Operações. */
function ActionRow({ cpeId, a }: { cpeId: string; a: CpeAction }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const key = useRef(`ui-${crypto.randomUUID()}`); // um pedido por abertura do painel: clique duplo não cria dois
  const trigger = useRef<HTMLButtonElement>(null);
  const close = () => { setOpen(false); setError(null); trigger.current?.focus(); };

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const ssid = a.needs_params ? String(new FormData(e.currentTarget).get("ssid") ?? "").trim() : undefined;
    setBusy(true); setError(null);
    try {
      const res = await fetch(`/bff/cpes/${cpeId}/actions/${a.operation}`, {
        method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify({ key: key.current, ssid }),
      });
      const j = (await res.json().catch(() => ({}))) as { error?: string; outcome?: string; reason?: string | null; job_id?: string | null };
      if (res.ok) { setResult({ kind: j.outcome === "blocked" ? "blocked" : "submitted", reason: j.reason ?? null, jobId: j.job_id ?? null }); key.current = `ui-${crypto.randomUUID()}`; return; }
      setError(ACTION_ERROR[j.error ?? "failed"] ?? ACTION_ERROR.failed);
    } catch { setError(ACTION_ERROR.failed); } finally { setBusy(false); }
  }

  return (
    <li className="grid gap-1 py-3" data-testid={`cpe-action-${a.operation}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="font-medium">{a.label}</div>
          {!a.offered && <div className="text-xs text-muted" data-testid="action-unavailable">Indisponível: {ACTION_UNAVAILABLE[a.reason ?? ""] ?? "não oferecida."}</div>}
        </div>
        {a.offered && <button ref={trigger} type="button" onClick={() => { setResult(null); setOpen(true); }} aria-haspopup="dialog" data-testid="action-open"
          className="min-h-touch rounded-btn border border-line px-3 text-sm hover:bg-bg">Pedir…</button>}
      </div>
      <EntityDetailDrawer open={open} onClose={close} title={a.label}>
        {result ? (
          <div className="grid gap-3 text-sm" data-testid="action-result" role="status">
            {result.kind === "submitted"
              ? <p><strong>Pedido criado.</strong> Ele aguarda a aprovação em Operações, pelas regras de lá. Nada foi executado no equipamento.</p>
              : <p><strong>O pedido não seguiu.</strong> {ACTION_BLOCKED[result.reason ?? ""] ?? "O motor de operações recusou. Nada foi enviado."}</p>}
            {result.jobId && <Link href="/operacoes" className="inline-flex min-h-touch items-center text-accent hover:underline">Ver em Operações</Link>}
            <button type="button" onClick={close} className="min-h-touch rounded-btn border border-line px-3">Fechar</button>
          </div>
        ) : (
          <form onSubmit={submit} className="grid gap-4 text-sm" data-testid="action-form">
            <div role="note" className="rounded-btn border border-line bg-bg p-3">
              <p className="font-medium">O que acontece</p>
              <ul className="mt-1 list-disc pl-5 text-muted">
                <li>Isto só <strong>cria um pedido de operação</strong>; nada é enviado ao equipamento agora.</li>
                <li>O pedido é aprovado em Operações pelas regras de lá. Hoje nenhuma escrita está homologada; só o equipamento de bancada, com a autorização prévia do responsável, chega a seguir (nele, quem pediu pode aprovar: a decisão é a autorização do responsável).</li>
                <li>Se o motor de operações não deixar o pedido seguir, ele é cancelado e você vê o motivo.</li>
              </ul>
            </div>
            {a.needs_params && (
              <label className="grid gap-1">Novo nome do Wi-Fi (bancada: começa com BANCADA-)
                <input name="ssid" required pattern="BANCADA-[A-Z0-9]{1,16}" maxLength={25} className="min-h-touch rounded-btn border border-line bg-bg px-3 font-mono" />
              </label>
            )}
            {error && <p role="alert" data-testid="action-error" className="text-danger">{error}</p>}
            <button type="submit" disabled={busy} className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">{busy ? "Pedindo…" : "Criar pedido"}</button>
          </form>
        )}
      </EntityDetailDrawer>
    </li>
  );
}

export function CpeActions({ cpeId, actions }: { cpeId: string; actions: CpeAction[] }) {
  return <ul className="divide-y divide-line text-sm" data-testid="cpe-actions-list">{actions.map((a) => <ActionRow key={a.operation} cpeId={cpeId} a={a} />)}</ul>;
}
