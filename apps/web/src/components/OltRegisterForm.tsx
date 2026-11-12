"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ConnectionFields } from "@/components/ConnectionFields";
import { PopCombobox } from "@/components/PopCombobox";
import { ADDRESS_HELP, CRED_HELP, FLEET_FLASH, FLEET_VENDORS, SNMP_VERSIONS, type Pop } from "@/lib/fleet";
import { EDGE_VENDORS, VENDOR_WARNING } from "@/lib/oltConnection";
import { setDraftAddress } from "@/lib/oltDraft";
import type { Edge } from "@/lib/types";

const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

/**
 * Passo 1 do assistente (ADR-0046 D3): cadastrar a OLT na nuvem. É um formulário NATIVO (funciona sem JavaScript, igual ao que já existia); com JavaScript, o botão "Cadastrar e continuar" envia por fetch,
 * guarda o endereço digitado só na MEMÓRIA do módulo (nunca localStorage/sessionStorage/URL) e leva à página da OLT, onde o passo 2 já vem preenchido. Nada aqui é segredo: login, senha e community ficam no passo 3.
 */
export function OltRegisterForm({ edges, pops, secretsOn, provisionOn }: { edges: Edge[]; pops: Pop[]; secretsOn: boolean; provisionOn: boolean }) {
  const router = useRouter();
  const [vendor, setVendor] = useState("huawei");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const none = edges.length === 0;

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    const submitter = (e.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    if (submitter?.value !== "assistente") return;   // os outros botões seguem o envio nativo (recarrega a página com o aviso)
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      const fd = new FormData(e.currentTarget);
      const body: Record<string, string> = {};
      for (const [k, v] of fd.entries()) if (typeof v === "string") body[k] = v;
      const r = await fetch("/bff/frota/olts", { method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      const j = (await r.json().catch(() => null)) as { id?: string; detail?: string } | null;
      if (r.status === 201 && j?.id) {
        if (body.mgmt_address) setDraftAddress(j.id, body.mgmt_address);
        router.push(`/rede/frota/${j.id}?ok=oltassistente#passos`);
        return;
      }
      setErr(FLEET_FLASH[j?.detail ?? ""] ?? FLEET_FLASH.falha);
    } catch {
      setErr(FLEET_FLASH.falha);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form method="post" action="/bff/frota/olts" onSubmit={(e) => void onSubmit(e)} className="grid gap-3 md:grid-cols-2">
      <label className="grid gap-1 text-sm">Nome da OLT<input name="name" required minLength={2} maxLength={60} className={field} placeholder="ex.: OLT-CENTRO-01" /></label>
      <label className="grid gap-1 text-sm">Fabricante<select name="vendor" required value={vendor} onChange={(e) => setVendor(e.target.value)} className={field}>{FLEET_VENDORS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        {!EDGE_VENDORS.includes(vendor) && <span className="text-xs text-muted" data-testid="frota-fabricante-aviso">{VENDOR_WARNING}</span>}</label>
      <label className="grid gap-1 text-sm">Edge que vai coletar<select name="edge_id" required className={field}>{edges.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
      <PopCombobox pops={pops.map((p) => ({ id: p.id, name: p.name }))} />
      <label className="grid gap-1 text-sm">Endereço de gerência (opcional)<input name="mgmt_address" maxLength={45} autoComplete="off" spellCheck={false} inputMode="text" className={`${field} font-mono`} placeholder="ex.: 10.20.30.40" />
        <span className="text-xs text-muted">{ADDRESS_HELP}</span></label>
      <label className="grid gap-1 text-sm">Versão do SNMP (opcional)<select name="snmp_version" className={field}><option value="">Não informar</option>{SNMP_VERSIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      <ConnectionFields defaults={{ protocol: null, port: null, transport: "cli", snmp_port: null, host_key_sha256: null, ssh_mode: "exec", legacy_ssh: false }} />
      <label className="grid gap-1 text-sm">Rótulo (opcional)<input name="label" maxLength={80} className={field} /></label>
      <label className="grid gap-1 text-sm">Nome da credencial no Edge (opcional)<input name="credential_ref" maxLength={64} autoComplete="off" spellCheck={false} className={`${field} font-mono`} placeholder="ex.: olt-centro-01" />
        <span className="text-xs text-muted">{CRED_HELP}</span></label>
      <div className="flex flex-wrap items-center gap-3 md:col-span-2">
        {provisionOn && <button type="submit" name="acao" value="assistente" data-testid="frota-cadastrar-continuar" className="min-h-touch rounded-btn border border-accent px-4 text-sm font-medium text-accent hover:bg-bg disabled:opacity-60" disabled={none || busy}>{busy ? "Cadastrando…" : "Cadastrar e continuar"}</button>}
        <button type="submit" data-testid="frota-cadastrar" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg" disabled={none}>Cadastrar OLT</button>
        <button type="submit" name="acao" value="testar" data-testid="frota-cadastrar-testar" className="min-h-touch rounded-btn border border-accent px-4 text-sm text-accent hover:bg-bg" disabled={none}>Cadastrar e testar conexão</button>
        {secretsOn && <button type="submit" name="acao" value="credenciais" data-testid="frota-cadastrar-credenciais" className="min-h-touch rounded-btn border border-accent px-4 text-sm text-accent hover:bg-bg" disabled={none}>Cadastrar e configurar credenciais</button>}
        {none && <span className="ml-3 text-xs text-muted">Nenhum Edge disponível.</span>}
      </div>
      <div aria-live="polite" className="md:col-span-2" data-testid="frota-cadastro-msg">{err && <p role="alert" className="rounded-btn border border-danger px-3 py-2 text-sm text-danger">{err}</p>}</div>
    </form>
  );
}
