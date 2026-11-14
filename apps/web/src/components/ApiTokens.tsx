"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { MfaStepUp } from "@/components/MfaStepUp";
import { SecretValue } from "@/components/SecretValue";
import { PERMISSION_LABEL, STATE_LABEL, clampDays } from "@/lib/integrations";
import { TEAM_ERROR, when } from "@/lib/team";
import type { ApiTokenList } from "@/lib/types";

/** Tokens de API (ADR-0051 D1): integrações de LEITURA que não são uma pessoa. O token aparece uma vez, na criação. */
export function ApiTokens({ data }: { data: ApiTokenList }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needStepUp, setNeedStepUp] = useState(false);
  const [created, setCreated] = useState<{ token: string; name: string } | null>(null);
  const [perms, setPerms] = useState<string[]>([]);
  const [confirmRevoke, setConfirmRevoke] = useState<string | null>(null);
  const retry = useRef<(() => Promise<void>) | null>(null);
  const active = data.items.filter((t) => t.state === "active").length;

  async function call(fn: () => Promise<Response>, ok: (j: Record<string, unknown>) => void) {
    retry.current = () => call(fn, ok); setBusy(true); setError(null);
    try {
      const res = await fn();
      const j = (await res.json().catch(() => ({}))) as Record<string, unknown>;
      if (res.ok) { setNeedStepUp(false); ok(j); return; }
      if (j.error === "mfa_recent_required") { setNeedStepUp(true); return; }
      setError(TEAM_ERROR[String(j.error ?? "failed")] ?? TEAM_ERROR.failed);
    } catch { setError(TEAM_ERROR.failed); } finally { setBusy(false); }
  }
  const create = (fd: FormData) => {
    const body = { name: String(fd.get("name") ?? "").trim(), permissions: perms, days: clampDays(Number(fd.get("days"))) };
    return call(() => fetch("/bff/tokens", { method: "POST", headers: { "content-type": "application/json" }, cache: "no-store", body: JSON.stringify(body) }),
      (j) => { setCreated({ token: String(j.token), name: body.name }); setPerms([]); router.refresh(); });
  };
  const revoke = (id: string) => call(() => fetch(`/bff/tokens/${id}`, { method: "DELETE", headers: { "content-type": "application/json" }, cache: "no-store", body: "{}" }), () => { setConfirmRevoke(null); router.refresh(); });

  return (
    <div className="grid gap-6" data-testid="api-tokens">
      <p role="note" className="panel p-3 text-sm" data-testid="tokens-readonly"><strong>Só leitura.</strong> Um token nunca escreve, nunca vê clientes, equipe nem auditoria, e só enxerga esta organização. Use <code>Authorization: Bearer fcat_…</code> nas rotas de leitura que ele cobre.</p>
      {error && <p role="alert" data-testid="tokens-error" className="text-danger">{error}</p>}
      {needStepUp && <MfaStepUp onDone={() => retry.current && void retry.current()} />}
      {created && (
        <div className="grid gap-3" data-testid="token-created">
          <SecretValue value={created.token} title={`Token “${created.name}”`} hint="Use no cabeçalho Authorization: Bearer. Se perder, revogue e crie outro." />
          <button type="button" onClick={() => setCreated(null)} className="min-h-touch w-fit rounded-btn border border-line px-4 text-sm">Já guardei o token</button>
        </div>
      )}
      <form onSubmit={(e) => { e.preventDefault(); void create(new FormData(e.currentTarget)); e.currentTarget.reset(); }} className="panel grid gap-4 p-4 text-sm" data-testid="token-form">
        <h2 className="font-semibold">Criar token</h2>
        <label className="grid gap-1">Nome (para você reconhecer depois)<input name="name" required minLength={2} maxLength={60} autoComplete="off" className="min-h-touch rounded-btn border border-line bg-bg px-3" /></label>
        <fieldset className="grid gap-1">
          <legend className="mb-1 font-medium">O que ele pode ler</legend>
          {data.allowed_permissions.map((p) => (
            <label key={p} className="flex min-h-touch items-start gap-2" data-testid={`token-perm-${p}`}>
              <input type="checkbox" className="mt-1 size-4" checked={perms.includes(p)} onChange={(e) => setPerms(e.target.checked ? [...perms, p] : perms.filter((x) => x !== p))} />
              <span>{PERMISSION_LABEL[p]?.label ?? p}<span className="block text-xs text-muted">{PERMISSION_LABEL[p]?.hint ?? ""}</span></span>
            </label>
          ))}
        </fieldset>
        <label className="grid gap-1">Validade em dias (1 a {data.max_days})<input name="days" type="number" min={1} max={data.max_days} defaultValue={90} required className="min-h-touch w-32 rounded-btn border border-line bg-bg px-3" /></label>
        <button type="submit" disabled={busy || perms.length === 0 || active >= data.max_active} data-testid="token-create" className="min-h-touch w-fit rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-60">Criar token</button>
        {active >= data.max_active && <p className="text-warn">Limite de {data.max_active} tokens ativos atingido. Revogue um antes de criar outro.</p>}
      </form>
      <section aria-labelledby="h-toks">
        <h2 id="h-toks" className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Tokens ({active} ativos)</h2>
        {data.items.length === 0 ? <p className="panel p-4 text-sm text-muted">Nenhum token ainda.</p> : (
          <ul className="panel divide-y divide-line" data-testid="token-list">
            {data.items.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm" data-testid={`token-${t.name}`}>
                <div className="min-w-0">
                  <div className="font-medium">{t.name} <code className="text-xs text-muted">fcat_{t.prefix}…</code> <span className="rounded-btn border border-line px-2 text-xs">{STATE_LABEL[t.state]}</span></div>
                  <div className="text-xs text-muted">{t.permissions.map((p) => PERMISSION_LABEL[p]?.label ?? p).join(", ")} · vale até {when(t.expires_at)} · {t.last_used_at ? `usado por último em ${when(t.last_used_at)}` : "nunca usado"}</div>
                </div>
                {t.state === "active" && (confirmRevoke === t.id ? (
                  <span className="flex flex-wrap items-center gap-2">
                    <span>Revogar agora?</span>
                    <button type="button" disabled={busy} onClick={() => void revoke(t.id)} data-testid="token-revoke-yes" className="min-h-touch rounded-btn bg-danger px-3 text-[color:var(--on-accent)] disabled:opacity-60">Revogar</button>
                    <button type="button" onClick={() => setConfirmRevoke(null)} className="min-h-touch rounded-btn border border-line px-3">Voltar</button>
                  </span>
                ) : <button type="button" onClick={() => setConfirmRevoke(t.id)} data-testid="token-revoke" aria-label={`Revogar o token ${t.name}`} className="min-h-touch rounded-btn border border-line px-3 text-danger hover:bg-bg">Revogar</button>)}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
