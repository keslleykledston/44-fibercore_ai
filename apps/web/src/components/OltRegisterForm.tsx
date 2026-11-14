"use client";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ConnectionFields } from "@/components/ConnectionFields";
import { FormHelp } from "@/components/FormHelp";
import { PopCombobox } from "@/components/PopCombobox";
import { ADDRESS_HELP, CRED_HELP, FLEET_FLASH, FLEET_VENDORS, SNMP_VERSIONS, fleetErrorText, type Pop } from "@/lib/fleet";
import { connectionPlain, DEFAULT_PORT, EDGE_VENDORS, hostKeyProblem, ipLiteralProblem, portProblem, TRUST_COMMAND, VENDOR_WARNING } from "@/lib/oltConnection";
import { fetchSealKey, sealAndDeliver, sealSupported } from "@/lib/oltDeliver";
import { plainProblem, type Plain } from "@/lib/oltSeal";
import { clearDraftAddress, setDraftAddress } from "@/lib/oltDraft";
import type { Edge } from "@/lib/types";

const field = "min-h-touch rounded-btn border border-line bg-bg px-3";
type StepState = "wait" | "run" | "ok" | "error" | "skip";
type Prog = { key: string; label: string; state: StepState; note?: string };
const MARK: Record<StepState, string> = { wait: "○", run: "●", ok: "✓", error: "▲", skip: "–" };
const TONE: Record<StepState, string> = { wait: "text-muted", run: "text-accent", ok: "text-ok", error: "text-danger", skip: "text-muted" };

/**
 * Passo 1 do assistente (ADR-0046 D3): cadastrar a OLT na nuvem. É um formulário NATIVO (funciona sem JavaScript, igual ao que já existia); com JavaScript, o botão "Cadastrar e continuar" envia por fetch,
 * guarda o endereço digitado só na MEMÓRIA do módulo (nunca localStorage/sessionStorage/URL) e leva à página da OLT, onde o passo 2 já vem preenchido. Nada aqui é segredo: login, senha e community ficam no passo 3.
 */
export function OltRegisterForm({ edges, pops, secretsOn, provisionOn }: { edges: Edge[]; pops: Pop[]; secretsOn: boolean; provisionOn: boolean }) {
  const router = useRouter();
  const [vendor, setVendor] = useState("huawei");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);   // trava síncrona: dois envios antes de o React renderizar `busy` não passam
  const [err, setErr] = useState<string | null>(null);
  const none = edges.length === 0;
  const [sealOk, setSealOk] = useState(false);
  const [conn, setConn] = useState({ protocol: "", transport: "cli" });
  const [prog, setProg] = useState<Prog[] | null>(null);
  const [done, setDone] = useState<{ id: string; name: string; trust: boolean } | null>(null);
  const [failedId, setFailedId] = useState<string | null>(null);
  const userRef = useRef<HTMLInputElement>(null), passRef = useRef<HTMLInputElement>(null), commRef = useRef<HTMLInputElement>(null);
  useEffect(() => { setSealOk(sealSupported()); }, []);
  const onConn = useCallback((v: { protocol: string; transport: string }) => setConn(v), []);
  const clearSecrets = () => { for (const r of [userRef, passRef, commRef]) if (r.current) r.current.value = ""; };
  const sshSelected = conn.protocol === "ssh", snmpSelected = sshSelected && conn.transport === "snmp";
  const showSecrets = provisionOn && secretsOn && sealOk && sshSelected;

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    if (lock.current || busy) { e.preventDefault(); return; }   // um cadastro em andamento: nenhum botão do formulário (nativo ou não) envia outro
    const submitter = (e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    if (submitter?.value === "tudo") { e.preventDefault(); void runAll(new FormData(e.currentTarget)); return; }
    if (submitter?.value !== "assistente") return;   // os outros botões seguem o envio nativo (recarrega a página com o aviso)
    e.preventDefault();
    lock.current = true;
    setBusy(true);
    setErr(null);
    try {
      const fd = new FormData(e.currentTarget);
      const body: Record<string, string> = {};
      for (const [k, v] of fd.entries()) if (typeof v === "string") body[k] = v;
      const r = await fetch("/bff/frota/olts", { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const j = (await r.json().catch(() => null)) as { id?: string; detail?: string; atual?: unknown; max?: unknown } | null;
      if (r.status === 201 && j?.id) {
        if (body.mgmt_address) setDraftAddress(j.id, body.mgmt_address);
        router.push(`/rede/frota/${j.id}?ok=oltassistente#passos`);
        return;
      }
      setErr(fleetErrorText(j));
    } catch {
      setErr(FLEET_FLASH.falha);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  /**
   * Formulário único (ADR-0046 D3): cadastra, entrega a conexão e entrega a credencial em sequência, com o progresso de cada passo. Tudo o que é segredo (login, senha, community) é cifrado AQUI, com a chave do Edge,
   * e só o texto cifrado sai do navegador; os campos são apagados antes de a requisição de credencial sair. Se um passo falha, o que já foi feito fica e cada passo pode ser reenviado na página da OLT sem refazer os outros.
   */
  async function runAll(fd: FormData) {
    if (busy || lock.current) return;
    const f = (k: string) => String(fd.get(k) ?? "").trim();
    const address = f("mgmt_address"), edgeId = f("edge_id"), vendorName = f("vendor"), oltName = f("name");
    const port = f("mgmt_port") || String(DEFAULT_PORT.ssh);
    const transport = f("mgmt_transport") === "snmp" ? "snmp" : "cli";
    setErr(null); setDone(null); setFailedId(null);
    // validação local antes de qualquer envio (a mesma que o servidor e o Edge fazem; nada disto repete o valor digitado)
    let bad: string | null = null;
    if (f("mgmt_protocol") !== "ssh") bad = "Escolha o protocolo SSH. Telnet é só cadastro: use “Cadastrar OLT”.";
    else if ((bad = ipLiteralProblem(address)) !== null) bad = `Endereço de gerência: ${bad}`;
    else if ((bad = portProblem(port)) !== null) bad = `Porta de acesso: ${bad}`;
    else if ((bad = hostKeyProblem(f("host_key_sha256"))) !== null) bad = `Impressão digital do host: ${bad}`;
    let secret: Plain | null = null;
    if (!bad && showSecrets) {
      secret = transport === "snmp" ? { kind: "snmp_community", community: commRef.current?.value ?? "" } : { kind: "ssh_login", username: userRef.current?.value ?? "", password: passRef.current?.value ?? "" };
      bad = plainProblem(secret);
    }
    if (bad) { setErr(bad); return; }
    const withCred = secret !== null;
    const steps: Prog[] = [
      { key: "cadastro", label: "Cadastrar na nuvem", state: "wait" },
      { key: "conexao", label: "Cifrar e entregar a conexão ao Edge", state: "wait" },
      { key: "credencial", label: transport === "snmp" ? "Cifrar e entregar a community SNMP" : "Cifrar e entregar login e senha", state: withCred ? "wait" : "skip", note: withCred ? undefined : secretsOn ? "Sem campo de credencial neste navegador (precisa de https e WebCrypto): envie na página da OLT." : "O recurso Credenciais da OLT está desligado para este provedor." },
      { key: "confirmacao", label: "Confirmação no Edge (feita por quem administra o Edge)", state: "wait" },
    ];
    const set = (key: string, state: StepState, note?: string) => { const i = steps.findIndex((x) => x.key === key); steps[i] = { ...steps[i], state, note }; setProg([...steps]); };
    lock.current = true;
    setBusy(true);
    setProg([...steps]);
    try {
      // 0) a chave do Edge: sem ela confirmada o cadastro é feito, mas as entregas ficam para a página da OLT
      const kr = await fetchSealKey(edgeId);
      set("cadastro", "run");
      const body: Record<string, string> = {};
      for (const [k, v] of fd.entries()) if (typeof v === "string") body[k] = v;
      const r = await fetch("/bff/frota/olts", { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const j = (await r.json().catch(() => null)) as { id?: string; detail?: string; atual?: unknown; max?: unknown } | null;
      if (r.status !== 201 || !j?.id) { const t = fleetErrorText(j); set("cadastro", "error", t); for (const k of ["conexao", "credencial", "confirmacao"]) if (steps.find((x) => x.key === k)!.state === "wait") set(k, "skip", "Não feito: o cadastro falhou."); return; }
      const id = j.id;
      set("cadastro", "ok");
      setDraftAddress(id, address);   // só em memória: se algo falhar, a página da OLT já traz o endereço no passo da conexão
      setFailedId(id);
      const stop = (from: string, text: string) => {
        let after = false;
        for (const s of steps) { if (s.key === from) { after = true; continue; } if (after && s.state === "wait") set(s.key, "skip", "Não feito: reenvie na página da OLT."); }
        set(from, "error", text);
      };
      if (!kr.ok) { stop("conexao", kr.unconfirmed ? "A chave do Edge ainda não foi confirmada. Abra a OLT, confirme a impressão digital da chave e envie a conexão e a credencial." : kr.text); router.refresh(); return; }
      set("conexao", "run");
      const built = connectionPlain({ id, vendor: vendorName, connection: { protocol: "ssh", port: Number(port), transport, snmp_port: f("snmp_port") ? Number(f("snmp_port")) : null, host_key_sha256: f("host_key_sha256"), ssh_mode: f("ssh_mode") === "shell" ? "shell" : "exec", legacy_ssh: ["1", "true", "on"].includes(f("legacy_ssh")), trust_state: "none", applied: false, applied_at: null } }, address);
      if ("problem" in built) { stop("conexao", built.problem); router.refresh(); return; }
      const c1 = await sealAndDeliver({ oltId: id, oltName, key: kr.key, plain: built.plain });
      if (!c1.ok) { stop("conexao", c1.text); router.refresh(); return; }
      set("conexao", "ok", "Enviada cifrada. O Edge a aplica no próximo ciclo.");
      if (withCred && secret) {
        set("credencial", "run");
        const c2 = await sealAndDeliver({ oltId: id, oltName, key: kr.key, plain: secret, beforeSend: clearSecrets });
        if (!c2.ok) { stop("credencial", c2.text); router.refresh(); return; }
        set("credencial", "ok", "Enviada cifrada. O Edge a guarda; só a usa depois da confirmação.");
      }
      set("confirmacao", "run", "Aguardando quem administra o Edge. Nada é conectado antes disso.");
      clearDraftAddress(id);
      setFailedId(null);
      setDone({ id, name: oltName, trust: true });
      router.refresh();
    } catch {
      setErr(`${FLEET_FLASH.falha} Se a resposta se perdeu, a OLT pode ter sido cadastrada: confira na lista antes de tentar de novo (o nome não pode repetir).`);
    } finally {
      clearSecrets();   // aconteça o que acontecer, o texto claro não fica nos campos
      lock.current = false;
      setBusy(false);
    }
  }

  return (
    <form method="post" action="/bff/frota/olts" onSubmit={(e) => void onSubmit(e)} className="grid gap-x-3 gap-y-2 md:grid-cols-6">
      <label className="grid gap-1 text-sm md:col-span-2">Nome da OLT<input name="name" required minLength={2} maxLength={60} className={field} placeholder="ex.: OLT-CENTRO-01" /></label>
      <label className="grid gap-1 text-sm md:col-span-2">Fabricante<select name="vendor" required value={vendor} onChange={(e) => setVendor(e.target.value)} className={field}>{FLEET_VENDORS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      <label className="grid gap-1 text-sm md:col-span-2">Edge que vai coletar<select name="edge_id" required className={field}>{edges.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
      {!EDGE_VENDORS.includes(vendor) && <p className="text-xs text-muted md:col-span-6" data-testid="frota-fabricante-aviso">{VENDOR_WARNING}</p>}
      <div className="md:col-span-2"><PopCombobox pops={pops.map((p) => ({ id: p.id, name: p.name }))} /></div>
      <label className="grid gap-1 text-sm md:col-span-2">Endereço de gerência (opcional)<input name="mgmt_address" maxLength={45} autoComplete="off" spellCheck={false} inputMode="text" className={`${field} font-mono`} placeholder="ex.: 10.20.30.40" /></label>
      <label className="grid gap-1 text-sm md:col-span-2">Versão do SNMP (opcional)<select name="snmp_version" className={field}><option value="">Não informar</option>{SNMP_VERSIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      <ConnectionFields onChange={onConn} defaults={{ protocol: null, port: null, transport: "cli", snmp_port: null, host_key_sha256: null, ssh_mode: "exec", legacy_ssh: false }} />
      {showSecrets && (
        <fieldset className="grid gap-x-3 gap-y-2 md:col-span-6 md:grid-cols-6" data-testid="frota-segredos">
          <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">{snmpSelected ? "Community SNMP" : "Login e senha"} (cifrados neste navegador antes de sair)</legend>
          {snmpSelected ? (
            <label className="grid gap-1 text-sm md:col-span-3">Community SNMP (v2c)<input ref={commRef} type="password" autoComplete="off" spellCheck={false} maxLength={64} data-lpignore="true" data-1p-ignore data-testid="frota-community" className={`${field} font-mono`} /></label>
          ) : (
            <>
              <label className="grid gap-1 text-sm md:col-span-3">Login da OLT<input ref={userRef} type="password" autoComplete="off" spellCheck={false} maxLength={64} data-lpignore="true" data-1p-ignore data-testid="frota-login" className={`${field} font-mono`} /></label>
              <label className="grid gap-1 text-sm md:col-span-3">Senha da OLT<input ref={passRef} type="password" autoComplete="new-password" spellCheck={false} maxLength={128} data-lpignore="true" data-1p-ignore data-testid="frota-senha" className={`${field} font-mono`} /></label>
            </>
          )}
        </fieldset>
      )}
      <label className="grid gap-1 text-sm md:col-span-3">Rótulo (opcional)<input name="label" maxLength={80} className={field} /></label>
      <label className="grid gap-1 text-sm md:col-span-3">Nome da credencial no Edge (opcional)<input name="credential_ref" maxLength={64} autoComplete="off" spellCheck={false} className={`${field} font-mono`} placeholder="ex.: olt-centro-01" /></label>
      <FormHelp>
        <p><strong>Endereço.</strong> {ADDRESS_HELP}</p>
        <p><strong>Credencial.</strong> {CRED_HELP}</p>
        {showSecrets && <p><strong>Login, senha e community.</strong> Cifrados com a chave pública do Edge: a nuvem só guarda e repassa texto cifrado e nunca o devolve. Os campos são apagados ao enviar. Isto não troca a senha na OLT; só entrega a cópia que o Edge usa. Telnet não tem senha aqui.</p>}
      </FormHelp>
      <div className="flex flex-wrap items-center gap-2 md:col-span-6">
        {provisionOn && sealOk && sshSelected && <button type="submit" name="acao" value="tudo" data-testid="frota-cadastrar-tudo" className="min-h-touch rounded-btn bg-accent px-4 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60" disabled={none || busy}>{busy ? "Enviando…" : secretsOn ? "Cadastrar e enviar tudo ao Edge" : "Cadastrar e enviar a conexão ao Edge"}</button>}
        {provisionOn && <button type="submit" name="acao" value="assistente" data-testid="frota-cadastrar-continuar" className="min-h-touch rounded-btn border border-accent px-4 text-sm font-medium text-accent hover:bg-bg disabled:opacity-60" disabled={none || busy}>{busy ? "Cadastrando…" : "Cadastrar e continuar"}</button>}
        <button type="submit" data-testid="frota-cadastrar" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg disabled:opacity-60" disabled={none || busy}>Cadastrar OLT</button>
        <button type="submit" name="acao" value="testar" data-testid="frota-cadastrar-testar" className="min-h-touch rounded-btn border border-accent px-4 text-sm text-accent hover:bg-bg disabled:opacity-60" disabled={none || busy}>Cadastrar e testar conexão</button>
        {secretsOn && <button type="submit" name="acao" value="credenciais" data-testid="frota-cadastrar-credenciais" className="min-h-touch rounded-btn border border-accent px-4 text-sm text-accent hover:bg-bg disabled:opacity-60" disabled={none || busy}>Cadastrar e configurar credenciais</button>}
        {none && <span className="ml-3 text-xs text-muted">Nenhum Edge disponível.</span>}
      </div>
      {prog && (
        <ol className="grid gap-1 rounded-btn border border-line p-3 text-sm md:col-span-6" aria-label="Progresso do cadastro" data-testid="frota-progresso">
          {prog.map((p, n) => (
            <li key={p.key} data-testid={`frota-progresso-${p.key}`} data-state={p.state}>
              <span className={`font-medium ${TONE[p.state]}`}><span aria-hidden>{MARK[p.state]} </span>{n + 1}. {p.label}</span>
              {p.note && <span className={`block text-xs ${p.state === "error" ? "text-danger" : "text-muted"}`}>{p.note}</span>}
            </li>))}
        </ol>
      )}
      {failedId && !busy && <p className="text-sm md:col-span-6" data-testid="frota-progresso-abrir">A OLT foi cadastrada. <Link href={`/rede/frota/${failedId}#passos`} className="text-accent underline underline-offset-2">Abrir a OLT</Link> para reenviar o passo que faltou, sem refazer os outros.</p>}
      {done && (
        <div className="grid gap-1 rounded-btn border border-accent px-3 py-2 text-sm md:col-span-6" data-testid="frota-progresso-fim">
          <p><strong>Tudo enviado.</strong> Falta só a confirmação no Edge. No servidor do Edge, quem o administra roda:</p>
          <code className="select-all break-all rounded-btn bg-bg px-2 py-1 font-mono text-xs" data-testid="frota-progresso-comando">{TRUST_COMMAND(done.name)}</code>
          <p className="text-xs text-muted">Depois disso o Edge conecta e a OLT sai de “Aguardando confirmação”. Acompanhe e teste em <Link href={`/rede/frota/${done.id}#passos`} className="text-accent underline underline-offset-2">{done.name}</Link>.</p>
        </div>
      )}
      <div aria-live="polite" className="md:col-span-6" data-testid="frota-cadastro-msg">{err && <p role="alert" className="rounded-btn border border-danger px-3 py-2 text-sm text-danger">{err}</p>}</div>
    </form>
  );
}
