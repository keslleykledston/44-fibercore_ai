"use client";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { fingerprintOf, keyIdOf, plainProblem, SealError, sealOltSecret, type Plain, type SecretKind } from "@/lib/oltSeal";
import { codeText, KIND_PT, SEND_ERR_PT, STATUS_PT, type Delivery, type SealKey } from "@/lib/oltSecrets";

/**
 * Entrada segura de login/senha/community (ADR-0045). O texto claro:
 *  - só existe nos campos desta tela e dentro de `sealOltSecret` (WebCrypto: ECDH P-256 + HKDF + AES-256-GCM, no navegador);
 *  - sai daqui SOMENTE cifrado, para o BFF, que repassa à API (que só guarda o texto cifrado);
 *  - nunca vai para URL, localStorage/sessionStorage, console, estado do React, nem para o BFF/API em claro;
 *  - é apagado dos campos assim que a selagem termina (antes de a requisição sair).
 * Os campos NÃO são renderizados no servidor nem sem WebCrypto (sem JavaScript: mensagem de falha fechada), não têm `name` (nada seria serializado num envio nativo) e não existe script inline (CSP com nonce).
 */
type Phase = "checking" | "ready" | "unsupported";
type Msg = { tone: "ok" | "error"; text: string } | null;
const field = "min-h-touch rounded-btn border border-line bg-bg px-3";
const WINDOW_SECONDS = 1800;   // validade de uma entrega: 30 min (a API aceita até 60)
const OPEN = new Set(["PENDING", "DISPATCHED"]);

export function OltCredentials({ oltId, oltName, edgeId, snmpV3, initialItems, keyConfirmed }: { oltId: string; oltName: string; edgeId: string; snmpV3: boolean; initialItems: Delivery[]; keyConfirmed: boolean }) {
  const base = useId();
  const [phase, setPhase] = useState<Phase>("checking");
  const [kind, setKind] = useState<SecretKind>("ssh_login");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [items, setItems] = useState<Delivery[]>(initialItems);
  const userRef = useRef<HTMLInputElement>(null), passRef = useRef<HTMLInputElement>(null), commRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setPhase(globalThis.isSecureContext && !!globalThis.crypto?.subtle && typeof globalThis.crypto.randomUUID === "function" ? "ready" : "unsupported"); }, []);

  const clearFields = useCallback(() => { for (const r of [userRef, passRef, commRef]) if (r.current) r.current.value = ""; }, []);
  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`/bff/frota/olts/${oltId}/credenciais`, { cache: "no-store", credentials: "same-origin" });
      if (r.ok) setItems(((await r.json()) as { items: Delivery[] }).items);
    } catch { /* a lista só se atualiza quando a rede responde */ }
  }, [oltId]);
  const anyOpen = items.some((i) => OPEN.has(i.status));
  useEffect(() => {
    if (!anyOpen) return;
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [anyOpen, refresh]);

  async function send() {
    if (busy) return;
    setMsg(null);
    setBusy(true);
    try {
      const plain: Plain = kind === "ssh_login" ? { kind, username: userRef.current?.value ?? "", password: passRef.current?.value ?? "" } : { kind, community: commRef.current?.value ?? "" };
      const problem = plainProblem(plain);
      if (problem) { setMsg({ tone: "error", text: problem }); return; }
      // a chave vigente vem do servidor, mas o key_id e a impressão digital são recalculados AQUI a partir da chave que vai selar
      const kr = await fetch(`/bff/frota/edges/${edgeId}/chave`, { cache: "no-store", credentials: "same-origin" });
      if (!kr.ok) { setMsg({ tone: "error", text: kr.status === 401 ? SEND_ERR_PT.unauthorized : SEND_ERR_PT.falha }); return; }
      const key = (await kr.json()) as SealKey;
      if (key.state !== "confirmed" || !key.public_key || !key.key_id || key.edge_id !== edgeId) { setMsg({ tone: "error", text: SEND_ERR_PT.seal_key_not_confirmed }); return; }
      if ((await keyIdOf(key.public_key)) !== key.key_id) { setMsg({ tone: "error", text: "A chave recebida não é consistente com o seu identificador. Nada foi enviado." }); return; }
      const deliveryId = globalThis.crypto.randomUUID();
      const expiresAt = key.server_time + WINDOW_SECONDS;   // o relógio da nuvem, não o do navegador: a API só aceita até 60 min à frente
      const sealed = await sealOltSecret({ tenantId: key.tenant_id, edgeId: key.edge_id, oltName, deliveryId, keyId: key.key_id, expiresAtUnix: expiresAt, edgePublicKey: key.public_key, plain });
      clearFields();   // o texto claro não é mais necessário: apaga antes de a requisição sair
      const r = await fetch(`/bff/frota/olts/${oltId}/credenciais`, {
        method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" },
        body: JSON.stringify({ delivery_id: deliveryId, kind, key_id: key.key_id, expires_at: expiresAt, sealed: sealed.sealed }),
      });
      if (r.status === 202) {
        setMsg({ tone: "ok", text: "Credencial cifrada e enviada. O Edge a aplica no próximo ciclo de consulta; o estado aparece na lista abaixo. Depois de aplicada, use “Testar conexão” para conferir." });
        await refresh();
      } else {
        const d = ((await r.json().catch(() => null)) as { detail?: string } | null)?.detail ?? "";
        setMsg({ tone: "error", text: SEND_ERR_PT[d] ?? SEND_ERR_PT.falha });
      }
    } catch (e) {
      // só um SealError (mensagem própria, sem o valor digitado) é mostrado; qualquer outra coisa vira texto genérico
      setMsg({ tone: "error", text: e instanceof SealError ? e.message : SEND_ERR_PT.falha });
    } finally {
      setBusy(false);
    }
  }

  if (phase !== "ready") {
    return (
      <p role="status" data-testid="cred-sem-js" className="rounded-btn border border-line px-3 py-2 text-sm text-muted">
        {/* é o que o servidor entrega e o que fica sem JavaScript: falha fechada, sem nenhum campo */}
        {phase === "unsupported" ? "Este navegador não oferece a criptografia necessária (WebCrypto em conexão segura). Por segurança a credencial não pode ser digitada aqui: use um navegador atual em https."
          : "Esta tela exige JavaScript e um navegador com WebCrypto (conexão segura) para cifrar a credencial antes de enviar. Sem isso nada é enviado e os campos não aparecem."}
      </p>
    );
  }
  const id = (s: string) => `${base}-${s}`;
  return (
    <div className="grid gap-4">
      <form onSubmit={(e) => { e.preventDefault(); void send(); }} method="post" autoComplete="off" noValidate className="grid gap-3" data-testid="cred-form" aria-label="Enviar credencial cifrada">
        <fieldset className="grid gap-2 text-sm">
          <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">O que enviar</legend>
          <label className="flex min-h-touch items-center gap-2"><input type="radio" className="h-6 w-6" checked={kind === "ssh_login"} onChange={() => { clearFields(); setKind("ssh_login"); }} /> {KIND_PT.ssh_login}</label>
          <label className="flex min-h-touch items-center gap-2"><input type="radio" className="h-6 w-6" checked={kind === "snmp_community"} disabled={snmpV3} onChange={() => { clearFields(); setKind("snmp_community"); }} /> {KIND_PT.snmp_community}</label>
          {snmpV3 && <p className="text-xs text-muted" data-testid="cred-v3">Esta OLT está cadastrada com SNMP v3, que o Edge ainda não suporta: só a community v2c seria usada, por isso ela não pode ser enviada.</p>}
        </fieldset>
        {kind === "ssh_login" ? (
          <>
            <label className="grid gap-1 text-sm" htmlFor={id("user")}>Login da OLT
              <input id={id("user")} ref={userRef} type="password" autoComplete="off" spellCheck={false} maxLength={64} data-lpignore="true" data-1p-ignore className={`${field} font-mono`} /></label>
            <label className="grid gap-1 text-sm" htmlFor={id("pass")}>Senha da OLT
              <input id={id("pass")} ref={passRef} type="password" autoComplete="new-password" spellCheck={false} maxLength={128} data-lpignore="true" data-1p-ignore className={`${field} font-mono`} /></label>
          </>
        ) : (
          <label className="grid gap-1 text-sm" htmlFor={id("comm")}>Community SNMP (v2c)
            <input id={id("comm")} ref={commRef} type="password" autoComplete="off" spellCheck={false} maxLength={64} data-lpignore="true" data-1p-ignore className={`${field} font-mono`} /></label>
        )}
        <p className="text-xs text-muted">Cifrado neste navegador com a chave pública do Edge: a nuvem só guarda e repassa texto cifrado e nunca devolve o segredo. Os campos são apagados ao enviar. Isto <strong>não troca a senha na OLT</strong>: só atualiza a cópia que o Edge usa.</p>
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" data-testid="cred-enviar" disabled={busy || !keyConfirmed} className="min-h-touch rounded-btn border border-accent px-4 text-sm text-accent hover:bg-bg disabled:opacity-60">{busy ? "Cifrando e enviando…" : "Cifrar e enviar ao Edge"}</button>
          {!keyConfirmed && <span className="text-xs text-muted">Confirme a impressão digital da chave do Edge para liberar o envio.</span>}
        </div>
        <div aria-live="polite" data-testid="cred-msg">{msg && <p role={msg.tone === "error" ? "alert" : "status"} className={`rounded-btn border px-3 py-2 text-sm ${msg.tone === "error" ? "border-danger text-danger" : "border-ok text-ok"}`}>{msg.text}</p>}</div>
      </form>
      <div>
        <h3 className="mb-1 flex flex-wrap items-center gap-3 text-xs font-semibold uppercase tracking-wide text-muted">Últimas entregas
          <button type="button" onClick={() => void refresh()} data-testid="cred-atualizar" className="min-h-touch rounded-btn px-2 text-xs normal-case tracking-normal text-accent underline underline-offset-2">Atualizar</button></h3>
        {items.length === 0 ? <p className="text-sm text-muted" data-testid="cred-vazio">Nenhuma entrega ainda.</p> : (
          <ul className="divide-y divide-line text-sm" data-testid="cred-entregas">{items.map((d) => (
            <li key={d.id} data-testid="cred-entrega" className="py-1.5">
              <span className="font-medium">{KIND_PT[d.kind] ?? d.kind}</span> · <span data-testid="cred-estado">{STATUS_PT[d.status] ?? d.status}</span> · <span data-testid="volatile">{new Date(d.created_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</span>
              {codeText(d.code) && <span className="block text-xs text-muted" data-testid="cred-codigo">{codeText(d.code)}</span>}
            </li>))}</ul>
        )}
      </div>
    </div>
  );
}

/** Mostra a impressão digital CALCULADA neste navegador a partir da chave pública (não confia no valor do servidor) e avisa se diferir do que o servidor exibiu. */
export function FingerprintCheck({ publicKey, serverFingerprint }: { publicKey: string; serverFingerprint: string }) {
  const [local, setLocal] = useState<string | null>(null);
  useEffect(() => { fingerprintOf(publicKey).then(setLocal, () => setLocal("")); }, [publicKey]);
  if (local === null) return null;
  if (local === "") return <p role="alert" className="text-sm text-danger" data-testid="cred-fp-erro">A chave publicada pelo Edge é inválida. Não confirme.</p>;
  return local === serverFingerprint
    ? <p className="text-xs text-muted" data-testid="cred-fp-local">Impressão digital recalculada neste navegador a partir da chave: confere.</p>
    : <p role="alert" className="text-sm text-danger" data-testid="cred-fp-diverge">Atenção: a impressão digital calculada neste navegador (<span className="font-mono">{local}</span>) difere da exibida pelo servidor. Não confirme.</p>;
}
