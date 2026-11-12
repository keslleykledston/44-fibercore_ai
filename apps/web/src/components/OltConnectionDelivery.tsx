"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { addressMatchesMask, connectionPlain, EDGE_VENDORS, HOST_KEY_HELP, TRUST_COMMAND, VENDOR_WARNING, type ConnView } from "@/lib/oltConnection";
import { clearDraftAddress, peekDraftAddress } from "@/lib/oltDraft";
import { keyIdOf, plainProblem, SealError, sealOltSecret } from "@/lib/oltSeal";
import { codeText, KIND_PT, SEND_ERR_PT, STATUS_PT, type Delivery, type SealKey } from "@/lib/oltSecrets";

/**
 * Passo 2 do assistente (ADR-0046 D4): entregar a CONEXÃO da OLT (endereço, porta, protocolo, impressão digital do host...) ao Edge, cifrada neste navegador pelo mesmo canal das credenciais.
 * Nada aqui é segredo, mas o endereço só volta mascarado da nuvem: por isso a pessoa o digita (ou ele vem do cadastro, só na MEMÓRIA desta aba) e a tela confere se a máscara bate com a do cadastro antes de selar.
 * Sem JavaScript/WebCrypto: nenhum campo aparece (falha fechada). O Edge só CONECTA depois que quem o administra confirma o host no servidor dele (`fibercore-edge managed-trust`).
 */
type Phase = "checking" | "ready" | "unsupported";
type Msg = { tone: "ok" | "error"; text: string } | null;
const field = "min-h-touch rounded-btn border border-line bg-bg px-3";
const WINDOW_SECONDS = 1800;
const OPEN = new Set(["PENDING", "DISPATCHED"]);
const KIND = "olt_connection";

export type ConnOlt = { id: string; name: string; vendor: string; edgeId: string; masked: string | null; connection: ConnView };

export function OltConnectionDelivery({ olt, keyConfirmed, initialItems }: { olt: ConnOlt; keyConfirmed: boolean; initialItems: Delivery[] }) {
  const base = useId();
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("checking");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg>(null);
  const [items, setItems] = useState<Delivery[]>(initialItems.filter((d) => d.kind === KIND));
  const [fromDraft, setFromDraft] = useState(false);
  const addrRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setPhase(globalThis.isSecureContext && !!globalThis.crypto?.subtle && typeof globalThis.crypto.randomUUID === "function" ? "ready" : "unsupported"); }, []);
  useEffect(() => {   // o endereço digitado no cadastro, se a navegação veio de lá (só memória do módulo)
    if (phase !== "ready") return;
    const d = peekDraftAddress(olt.id);
    if (d && addrRef.current) { addrRef.current.value = d; setFromDraft(true); }
  }, [phase, olt.id]);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`/bff/frota/olts/${olt.id}/credenciais`, { cache: "no-store", credentials: "same-origin" });
      if (r.ok) {
        const next = ((await r.json()) as { items: Delivery[] }).items.filter((d) => d.kind === KIND);
        setItems((prev) => { if (prev.some((p) => OPEN.has(p.status)) && !next.some((n) => OPEN.has(n.status))) router.refresh(); return next; });   // uma entrega terminou: a prontidão do servidor mudou
      }
    } catch { /* a lista só se atualiza quando a rede responde */ }
  }, [olt.id, router]);
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
      const typed = addrRef.current?.value ?? "";
      const built = connectionPlain({ id: olt.id, vendor: olt.vendor, connection: olt.connection }, typed);
      if ("problem" in built) { setMsg({ tone: "error", text: built.problem }); return; }
      if (olt.masked !== null && !addressMatchesMask(typed, olt.masked)) { setMsg({ tone: "error", text: `O endereço digitado não tem a mesma máscara do cadastro (${olt.masked}). Confira a digitação ou corrija o endereço no cadastro.` }); return; }
      const problem = plainProblem(built.plain);
      if (problem) { setMsg({ tone: "error", text: problem }); return; }
      const kr = await fetch(`/bff/frota/edges/${olt.edgeId}/chave`, { cache: "no-store", credentials: "same-origin" });
      if (!kr.ok) { setMsg({ tone: "error", text: kr.status === 401 ? SEND_ERR_PT.unauthorized : SEND_ERR_PT.falha }); return; }
      const key = (await kr.json()) as SealKey;
      if (key.state !== "confirmed" || !key.public_key || !key.key_id || key.edge_id !== olt.edgeId) { setMsg({ tone: "error", text: SEND_ERR_PT.seal_key_not_confirmed }); return; }
      if ((await keyIdOf(key.public_key)) !== key.key_id) { setMsg({ tone: "error", text: "A chave recebida não é consistente com o seu identificador. Nada foi enviado." }); return; }
      const deliveryId = globalThis.crypto.randomUUID();
      const expiresAt = key.server_time + WINDOW_SECONDS;   // o relógio da nuvem, não o do navegador
      const sealed = await sealOltSecret({ tenantId: key.tenant_id, edgeId: key.edge_id, oltName: olt.name, deliveryId, keyId: key.key_id, expiresAtUnix: expiresAt, edgePublicKey: key.public_key, plain: built.plain });
      if (addrRef.current) addrRef.current.value = "";
      clearDraftAddress(olt.id);
      setFromDraft(false);
      const r = await fetch(`/bff/frota/olts/${olt.id}/credenciais`, {
        method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" },
        body: JSON.stringify({ delivery_id: deliveryId, kind: KIND, key_id: key.key_id, expires_at: expiresAt, sealed: sealed.sealed }),
      });
      if (r.status === 202) {
        setMsg({ tone: "ok", text: "Conexão cifrada e enviada. O Edge a aplica no próximo ciclo; o estado aparece abaixo. Depois de aplicada, quem administra o Edge precisa confirmar o host no servidor dele." });
        await refresh();
      } else {
        const d = ((await r.json().catch(() => null)) as { detail?: string } | null)?.detail ?? "";
        setMsg({ tone: "error", text: SEND_ERR_PT[d] ?? SEND_ERR_PT.falha });
      }
    } catch (e) {
      setMsg({ tone: "error", text: e instanceof SealError ? e.message : SEND_ERR_PT.falha });
    } finally {
      setBusy(false);
    }
  }

  if (phase !== "ready") {
    return (
      <p role="status" data-testid="conn-sem-js" className="rounded-btn border border-line px-3 py-2 text-sm text-muted">
        {phase === "unsupported" ? "Este navegador não oferece a criptografia necessária (WebCrypto em conexão segura). Por segurança a conexão não pode ser entregue daqui: use um navegador atual em https."
          : "Esta etapa exige JavaScript e um navegador com WebCrypto (conexão segura) para cifrar a conexão antes de enviar. Sem isso nada é enviado e os campos não aparecem."}
      </p>
    );
  }
  const c = olt.connection;
  const id = (s: string) => `${base}-${s}`;
  const last = items[0];
  const awaiting = c.applied && c.trust_state !== "trusted";
  return (
    <div className="grid gap-3">
      <dl className="grid gap-1 text-sm sm:grid-cols-2" data-testid="conn-resumo" aria-label="O que será entregue">
        <div><dt className="text-xs text-muted">Protocolo · porta</dt><dd>{(c.protocol ?? "—").toUpperCase()} · {c.port ?? "—"}</dd></div>
        <div><dt className="text-xs text-muted">Coleta · porta SNMP</dt><dd>{c.transport === "snmp" ? "SNMP" : "Linha de comando (SSH)"} · {c.snmp_port ?? 161}</dd></div>
        <div className="sm:col-span-2"><dt className="text-xs text-muted">Impressão digital do host (proposta: o Edge só confia depois da confirmação local)</dt><dd className="break-all font-mono text-xs">{c.host_key_sha256 ?? "— (falta no cadastro)"}</dd></div>
        <div><dt className="text-xs text-muted">Modo SSH · legado</dt><dd>{c.ssh_mode ?? "exec"} · {c.legacy_ssh ? "sim" : "não"}</dd></div>
        <div><dt className="text-xs text-muted">Endereço no cadastro (mascarado)</dt><dd className="font-mono">{olt.masked ?? "não informado"}</dd></div>
      </dl>
      {!EDGE_VENDORS.includes(olt.vendor) && <p role="note" className="rounded-btn border border-line px-3 py-2 text-xs" data-testid="conn-fabricante">{VENDOR_WARNING}</p>}
      <form onSubmit={(e) => { e.preventDefault(); void send(); }} method="post" autoComplete="off" noValidate className="grid gap-3" data-testid="conn-form" aria-label="Entregar a conexão ao Edge">
        <label className="grid gap-1 text-sm" htmlFor={id("addr")}>Endereço de gerência da OLT
          <input id={id("addr")} ref={addrRef} type="text" inputMode="text" autoComplete="off" spellCheck={false} maxLength={45} className={`${field} font-mono`} placeholder="ex.: 10.20.30.40" />
          <span className="text-xs text-muted" data-testid="conn-endereco-ajuda">{fromDraft ? "Trazido do cadastro (só na memória desta página). " : "A nuvem só guarda e mostra o endereço mascarado: digite-o de novo para entregá-lo ao Edge. "}
            {olt.masked ? `Tem de começar como ${olt.masked}.` : ""}</span></label>
        <p className="text-xs text-muted">Cifrado neste navegador com a chave pública do Edge. O Edge só o aceita dentro da política local dele (redes e portas liberadas) e <strong>não conecta nem usa credencial</strong> até quem o administra rodar <code>fibercore-edge managed-trust</code> no servidor dele.</p>
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" data-testid="conn-enviar" disabled={busy || !keyConfirmed} className="min-h-touch rounded-btn border border-accent px-4 text-sm text-accent hover:bg-bg disabled:opacity-60">{busy ? "Cifrando e enviando…" : items.length > 0 ? "Reenviar a conexão ao Edge" : "Cifrar e entregar a conexão ao Edge"}</button>
          {!keyConfirmed && <span className="text-xs text-muted">Confirme a impressão digital da chave do Edge (cartão abaixo, <a href="#credenciais" className="text-accent underline underline-offset-2">chave do Edge</a>) para liberar o envio.</span>}
        </div>
        <div aria-live="polite" data-testid="conn-msg">{msg && <p role={msg.tone === "error" ? "alert" : "status"} className={`rounded-btn border px-3 py-2 text-sm ${msg.tone === "error" ? "border-danger text-danger" : "border-ok text-ok"}`}>{msg.text}</p>}</div>
      </form>
      {awaiting && (
        <div className="grid gap-1 rounded-btn border border-accent px-3 py-2 text-sm" data-testid="conn-confianca">
          <p><strong>{c.trust_state === "awaiting_local_trust" ? "Aguardando confirmação no Edge." : "Conexão aplicada; aguardando o Edge informar a confiança."}</strong> No servidor do Edge, quem o administra roda:</p>
          <code className="select-all break-all rounded-btn bg-bg px-2 py-1 font-mono text-xs" data-testid="conn-comando">{TRUST_COMMAND(olt.name)}</code>
          <p className="text-xs text-muted">O comando mostra o nome, <span className="font-mono">ip:porta</span>, o fabricante e a impressão digital proposta, e pede que ela seja <strong>digitada de novo</strong> (compare com a da OLT por um canal confiável). Para obter a impressão digital na rede da OLT: <code>{HOST_KEY_HELP}</code>.</p>
        </div>
      )}
      <div>
        <h4 className="mb-1 flex flex-wrap items-center gap-3 text-xs font-semibold uppercase tracking-wide text-muted">Últimos envios da conexão
          <button type="button" onClick={() => { void refresh(); router.refresh(); }} data-testid="conn-atualizar" className="min-h-touch rounded-btn px-2 text-xs normal-case tracking-normal text-accent underline underline-offset-2">Atualizar</button></h4>
        {items.length === 0 ? <p className="text-sm text-muted" data-testid="conn-vazio">Nenhum envio ainda.</p> : (
          <ul className="divide-y divide-line text-sm" data-testid="conn-entregas">{items.map((d) => (
            <li key={d.id} data-testid="conn-entrega" className="py-1.5">
              <span className="font-medium">{KIND_PT[d.kind] ?? d.kind}</span> · <span data-testid="conn-estado">{STATUS_PT[d.status] ?? d.status}</span> · <span data-testid="volatile">{new Date(d.created_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</span>
              {codeText(d.code) && <span className="block text-xs text-muted" data-testid="conn-codigo">{codeText(d.code)}</span>}
            </li>))}</ul>
        )}
        {last && last.status === "FAILED" && <p className="mt-1 text-xs text-muted">O que falhou pode ser reenviado acima sem refazer os outros passos.</p>}
      </div>
    </div>
  );
}
