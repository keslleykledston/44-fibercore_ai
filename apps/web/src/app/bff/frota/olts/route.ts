import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/fleet";
import { hostKeyProblem, portProblem } from "@/lib/oltConnection";

const ADDR = /^[0-9A-Fa-f:.]{2,45}$/;
const noStore = { "cache-control": "no-store" };
type Fields = { get(k: string): string | null };
const clip = (v: unknown, max: number) => String(v ?? "").trim().slice(0, max);

/** Monta o corpo da API a partir dos campos (formulário nativo ou JSON do cadastro com JavaScript). Devolve o código do problema (sem o valor digitado) ou o corpo. */
function build(f: Fields): { body: Record<string, unknown>; address: string } | { why: string } {
  const edge = clip(f.get("edge_id"), 40), pop = clip(f.get("pop_id"), 40);
  if (!UUID.test(edge) || (pop && !UUID.test(pop))) return { why: "invalido" };
  const body: Record<string, unknown> = { name: clip(f.get("name"), 60), edge_id: edge, vendor: clip(f.get("vendor"), 20) };
  const popName = clip(f.get("pop_name"), 60), addr = clip(f.get("mgmt_address"), 45), snmp = clip(f.get("snmp_version"), 4);
  if (addr && !ADDR.test(addr)) return { why: "invalido" };   // o endereço digitado nunca volta numa mensagem
  if (pop) body.pop_id = pop;                      // site existente escolhido na lista
  else if (popName) body.pop_name = popName;       // site digitado: a API o encontra pelo nome ou o cria junto com a OLT
  if (addr) body.mgmt_address = addr;
  if (snmp) body.snmp_version = snmp;
  const cred = clip(f.get("credential_ref"), 64), label = clip(f.get("label"), 80);
  if (cred) body.credential_ref = cred;
  if (label) body.label = label;
  // ADR-0046: como a OLT é alcançada. Telnet não leva impressão digital, modo SSH nem SSH legado.
  const proto = clip(f.get("mgmt_protocol"), 8);
  if (proto) {
    if (proto !== "ssh" && proto !== "telnet") return { why: "invalido" };
    body.mgmt_protocol = proto;
    const port = clip(f.get("mgmt_port"), 5);
    if (port) { if (portProblem(port)) return { why: "porta" }; body.mgmt_port = Number(port); }
    if (proto === "ssh") {
      const transport = clip(f.get("mgmt_transport"), 4), sp = clip(f.get("snmp_port"), 5), hk = clip(f.get("host_key_sha256"), 64), mode = clip(f.get("ssh_mode"), 5);
      if (transport) body.mgmt_transport = transport;
      if (sp) { if (portProblem(sp)) return { why: "porta" }; body.snmp_port = Number(sp); }
      if (hk) { if (hostKeyProblem(hk)) return { why: "impressaodigital" }; body.host_key_sha256 = hk; }
      if (mode) body.ssh_mode = mode;
      body.legacy_ssh = ["1", "true", "on"].includes(clip(f.get("legacy_ssh"), 5));
    }
  }
  return { body, address: addr };
}

/** Cadastra uma OLT (nuvem apenas: nada é enviado à OLT). O campo da credencial é um NOME, nunca um segredo; o valor não é repetido em nenhuma mensagem. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const asJson = (req.headers.get("content-type") ?? "").toLowerCase().startsWith("application/json");
  let fields: Fields;
  if (asJson) {
    const text = await req.text();
    if (text.length > 4096) return NextResponse.json({ detail: "too_large" }, { status: 413, headers: noStore });
    let j: Record<string, unknown>;
    try { j = JSON.parse(text) as Record<string, unknown>; } catch { return NextResponse.json({ detail: "invalido" }, { status: 422, headers: noStore }); }
    fields = { get: (k) => (j[k] === undefined || j[k] === null ? null : typeof j[k] === "boolean" ? (j[k] ? "1" : "") : String(j[k])) };
  } else {
    const f = await req.formData();
    fields = { get: (k) => { const v = f.get(k); return v === null ? null : String(v); } };
  }
  const reply = (status: number, why: string, extra: Record<string, unknown> = {}) => NextResponse.json({ detail: why, ...extra }, { status, headers: noStore });
  const built = build(fields);
  if ("why" in built) return asJson ? reply(422, built.why) : back(req, `/rede/frota?erro=${built.why}`);
  const r = await apiPost("/v1/fleet/olts", JSON.stringify(built.body), { "Content-Type": "application/json" });
  const detail = typeof (r.json as { detail?: unknown } | null)?.detail === "string" ? ((r.json as { detail: string }).detail) : "";
  if (r.status === 201) {
    const id = (r.json as { id?: string } | null)?.id;
    if (asJson) return id && UUID.test(id) ? NextResponse.json({ id }, { status: 201, headers: noStore }) : reply(502, "falha");
    const acao = fields.get("acao");
    if (acao === "assistente" && id && UUID.test(id)) return back(req, `/rede/frota/${id}?ok=oltassistente#passos`);   // sem JavaScript: a pessoa redigita o endereço no passo 2
    if (acao === "credenciais" && id && UUID.test(id)) return back(req, `/rede/frota/${id}?ok=oltcredenciais#credenciais`);   // cadastra e vai direto ao cartão de credenciais (a entrada segura é lá, nunca neste formulário)
    if (acao !== "testar" || !id || !UUID.test(id)) return back(req, "/rede/frota?ok=olt");
    // "Cadastrar e testar conexão": o teste é o mesmo do detalhe (leitura da identidade pelo Edge, com orçamento e cache); falhar aqui não desfaz o cadastro
    const t = await apiPost(`/v1/fleet/olts/${id}/connection-test`, undefined, { "Idempotency-Key": `fleet-${randomUUID()}` });
    const o = t.status === 200 ? (t.json as { outcome?: string } | null)?.outcome : null;
    return back(req, `/rede/frota/${id}?ok=${o === "cached" ? "oltcomtestecache" : o ? "oltcomteste" : "oltsemteste"}`);
  }
  const why = r.status === 403 ? (JSON.stringify(r.json ?? {}).includes("feature_disabled") ? "desligado" : "permissao") : r.status === 409 ? "nome"
    : r.status === 422 ? (["protocol_required", "telnet_has_no_ssh_fields"].includes(detail) ? "protocolo" : detail === "snmp_transport_needs_v2c" ? "snmpv2" : "invalido")
    : r.status === 404 ? (JSON.stringify(r.json ?? {}).includes("pop") ? "popinexistente" : "edge") : "falha";
  return asJson ? reply([403, 404, 409, 422].includes(r.status) ? r.status : 502, why) : back(req, `/rede/frota?erro=${why}`);
}
