"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { MfaStepUp } from "@/components/MfaStepUp";
import { SecretValue } from "@/components/SecretValue";
import { DISABLED_REASON, EVENT_LABEL, SIGNATURE_EXAMPLE, STATE_LABEL, failureText, urlProblem } from "@/lib/integrations";
import { TEAM_ERROR, when } from "@/lib/team";
import type { Webhook, WebhookDelivery, WebhookList } from "@/lib/types";

/** Webhooks de saída (ADR-0051 D2): URL https com NOME, eventos de um catálogo fechado, segredo mostrado uma vez. */
export function Webhooks({ data }: { data: WebhookList }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);
  const [secret, setSecret] = useState<{ value: string; title: string } | null>(null);
  const [events, setEvents] = useState<string[]>([]);
  const [open, setOpen] = useState<{ id: string; items: WebhookDelivery[] } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const retry = useRef<(() => Promise<void>) | null>(null);
  const json = { "content-type": "application/json" };

  async function call(fn: () => Promise<Response>, ok: (j: Record<string, unknown>) => void) {
    retry.current = () => call(fn, ok); setBusy(true); setError(null); setNotice(null);
    try {
      const res = await fn();
      const j = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (res.ok) { setNeedStepUp(false); ok(j); return; }
      if (j.error === "mfa_recent_required") { setNeedStepUp(true); return; }
      setError(TEAM_ERROR[String(j.error ?? "failed")] ?? TEAM_ERROR.failed);
    } catch { setError(TEAM_ERROR.failed); } finally { setBusy(false); }
  }
  const create = (fd: FormData) => {
    const name = String(fd.get("name") ?? "").trim(), url = String(fd.get("url") ?? "").trim();
    const p = urlProblem(url);
    if (p) { setError(TEAM_ERROR[p]); return Promise.resolve(); }
    return call(() => fetch("/bff/webhooks", { method: "POST", headers: json, cache: "no-store", body: JSON.stringify({ name, url, events }) }),
      (j) => { setSecret({ value: String(j.secret), title: `Segredo de “${name}”` }); setEvents([]); router.refresh(); });
  };
  const patch = (id: string, body: unknown, msg: string) => call(() => fetch(`/bff/webhooks/${id}`, { method: "PATCH", headers: json, cache: "no-store", body: JSON.stringify(body) }), () => { setNotice(msg); router.refresh(); });
  const rotate = (w: Webhook) => call(() => fetch(`/bff/webhooks/${w.id}/rotate`, { method: "POST", headers: json, cache: "no-store", body: "{}" }), (j) => setSecret({ value: String(j.secret), title: `Novo segredo de “${w.name}” (o antigo parou de valer)` }));
  const test = (w: Webhook) => call(() => fetch(`/bff/webhooks/${w.id}/test`, { method: "POST", headers: json, cache: "no-store", body: "{}" }), () => setNotice("Teste na fila. Veja o resultado em “Entregas recentes” em alguns segundos."));
  const remove = (id: string) => call(() => fetch(`/bff/webhooks/${id}`, { method: "DELETE", headers: json, cache: "no-store", body: "{}" }), () => { setConfirmDelete(null); router.refresh(); });
  async function deliveries(id: string) {
    try {
      const res = await fetch(`/bff/webhooks/${id}/deliveries`, { cache: "no-store" });
      const j = (await res.json().catch(() => ({}))) as { items?: WebhookDelivery[]; error?: string };
      if (res.ok) setOpen({ id, items: j.items ?? [] }); else setError(TEAM_ERROR[j.error ?? "failed"] ?? TEAM_ERROR.failed);
    } catch { setError(TEAM_ERROR.failed); }
  }

  return (
    <div className="grid gap-6" data-testid="webhooks">
      {!data.available && <p role="alert" data-testid="webhooks-unavailable" className="panel border-warn p-3 text-sm">Os webhooks ainda não estão disponíveis neste servidor: falta a chave de cifra dos segredos. Peça a quem opera a plataforma para configurá-la (<code>FIBERCORE_WEBHOOK_ENCRYPTION_KEY</code>).</p>}
      {error && <p role="alert" data-testid="webhooks-error" className="text-danger">{error}</p>}
      {notice && <p role="status" data-testid="webhooks-notice">{notice}</p>}
      {needStepUp && <MfaStepUp onDone={() => retry.current && void retry.current()} />}
      {secret && (
        <div className="grid gap-3" data-testid="webhook-secret">
          <SecretValue value={secret.value} title={secret.title} hint="Use para conferir a assinatura de cada chamada (veja “Como conferir a assinatura” abaixo)." />
          <button type="button" onClick={() => setSecret(null)} className="min-h-touch w-fit rounded-btn border border-line px-4 text-sm">Já guardei o segredo</button>
        </div>
      )}
      <form onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; void create(new FormData(f)).then(() => undefined); }} className="panel grid gap-4 p-4 text-sm" data-testid="webhook-form">
        <h2 className="font-semibold">Novo webhook</h2>
        <label className="grid gap-1">Nome<input name="name" required minLength={2} maxLength={60} autoComplete="off" className="min-h-touch rounded-btn border border-line bg-bg px-3" /></label>
        <label className="grid gap-1">URL (https, com o NOME do servidor)
          <input name="url" type="url" required maxLength={500} placeholder="https://hooks.exemplo.com.br/fibercore" autoComplete="off" className="min-h-touch rounded-btn border border-line bg-bg px-3" />
          <span className="text-xs text-muted">Não aceitamos endereço IP, “localhost” nem nomes internos: só servidores públicos.</span>
        </label>
        <fieldset className="grid gap-1">
          <legend className="mb-1 font-medium">Avisar quando</legend>
          {data.events.map((ev) => (
            <label key={ev} className="flex min-h-touch items-center gap-2" data-testid={`webhook-event-${ev}`}>
              <input type="checkbox" className="size-4" checked={events.includes(ev)} onChange={(e) => setEvents(e.target.checked ? [...events, ev] : events.filter((x) => x !== ev))} />{EVENT_LABEL[ev] ?? ev}
            </label>
          ))}
        </fieldset>
        <button type="submit" disabled={busy || !data.available || events.length === 0 || data.items.length >= data.max_endpoints} data-testid="webhook-create" className="min-h-touch w-fit rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">Criar webhook</button>
      </form>

      <section aria-labelledby="h-wh">
        <h2 id="h-wh" className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Webhooks ({data.items.length} de {data.max_endpoints})</h2>
        {data.items.length === 0 ? <p className="panel p-4 text-sm text-muted">Nenhum webhook ainda.</p> : (
          <ul className="grid gap-3" data-testid="webhook-list">
            {data.items.map((w) => (
              <li key={w.id} className="panel grid gap-2 p-4 text-sm" data-testid={`webhook-${w.name}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="font-medium">{w.name} <span className={`rounded-btn border px-2 text-xs ${w.active ? "border-ok text-ok" : "border-warn text-warn"}`}>{w.active ? "Ativo" : "Desligado"}</span></div>
                    <div className="break-all text-xs text-muted">{w.url}</div>
                    <div className="text-xs text-muted">{w.events.map((e) => EVENT_LABEL[e] ?? e).join(", ")}{w.consecutive_failures > 0 ? ` · ${w.consecutive_failures} ${w.consecutive_failures === 1 ? "falha seguida" : "falhas seguidas"}` : ""}{w.disabled_reason ? ` · ${DISABLED_REASON[w.disabled_reason] ?? "desligado"}` : ""}</div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" disabled={busy || !data.available} onClick={() => void test(w)} data-testid="webhook-test" className="min-h-touch rounded-btn border border-line px-3 hover:bg-bg disabled:opacity-60">Testar</button>
                    <button type="button" onClick={() => void deliveries(w.id)} data-testid="webhook-deliveries" className="min-h-touch rounded-btn border border-line px-3 hover:bg-bg">Entregas recentes</button>
                    <button type="button" disabled={busy} onClick={() => void patch(w.id, { active: !w.active }, w.active ? "Webhook desligado." : "Webhook religado.")} data-testid="webhook-toggle" className="min-h-touch rounded-btn border border-line px-3 hover:bg-bg disabled:opacity-60">{w.active ? "Desligar" : "Religar"}</button>
                    <button type="button" disabled={busy || !data.available} onClick={() => void rotate(w)} data-testid="webhook-rotate" className="min-h-touch rounded-btn border border-line px-3 hover:bg-bg disabled:opacity-60">Girar segredo</button>
                    {confirmDelete === w.id ? (
                      <span className="flex items-center gap-2"><button type="button" disabled={busy} onClick={() => void remove(w.id)} data-testid="webhook-delete-yes" className="min-h-touch rounded-btn bg-danger px-3 text-[color:var(--on-accent)]">Apagar mesmo</button><button type="button" onClick={() => setConfirmDelete(null)} className="min-h-touch rounded-btn border border-line px-3">Voltar</button></span>
                    ) : <button type="button" onClick={() => setConfirmDelete(w.id)} data-testid="webhook-delete" aria-label={`Apagar o webhook ${w.name}`} className="min-h-touch rounded-btn border border-line px-3 text-danger hover:bg-bg">Apagar</button>}
                  </div>
                </div>
                {open?.id === w.id && (
                  <div data-testid="delivery-list" className="rounded-btn bg-bg p-3">
                    {open.items.length === 0 ? <p className="text-muted">Nenhuma entrega ainda.</p> : (
                      <ul className="divide-y divide-line">
                        {open.items.map((d) => (
                          <li key={d.id} className="py-1 text-xs">{EVENT_LABEL[d.event_type] ?? d.event_type} · {STATE_LABEL[d.state]}{d.last_status ? ` (HTTP ${d.last_status})` : ""}{d.last_error ? ` — ${failureText(d.last_error)}` : ""} · {d.attempts} {d.attempts === 1 ? "tentativa" : "tentativas"} · {when(d.created_at)}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <details className="panel p-4 text-sm" data-testid="signature-help">
        <summary className="cursor-pointer font-medium">Como conferir a assinatura</summary>
        <div className="mt-2 grid gap-2">
          <p>Cada chamada traz o cabeçalho <code>X-FiberCore-Signature: t=&lt;unix&gt;,v1=&lt;hex&gt;</code>, onde <code>hex = HMAC-SHA256(segredo, &quot;&lt;t&gt;.&lt;corpo bruto&gt;&quot;)</code>. Recuse se <code>t</code> tiver mais de 5 minutos.</p>
          <pre className="overflow-x-auto rounded-btn bg-bg p-3 text-xs"><code>{SIGNATURE_EXAMPLE}</code></pre>
          <p className="text-muted">Responda 2xx em até 10 segundos. Sem 2xx tentamos de novo com espera crescente (até 8 vezes em 24 h); 10 falhas seguidas desligam o webhook. O corpo traz só ids e contagens: nunca nome nem dado de cliente.</p>
        </div>
      </details>
    </div>
  );
}
