import { NextResponse } from "next/server";
import { randomUUID } from "node:crypto";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/fleet";

const ADDR = /^[0-9A-Fa-f:.]{2,45}$/;
const s = (v: FormDataEntryValue | null, max: number) => String(v ?? "").trim().slice(0, max);

/** Cadastra uma OLT (nuvem apenas: nada é enviado à OLT). O campo da credencial é um NOME, nunca um segredo; o valor não é repetido em nenhuma mensagem. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const f = await req.formData();
  const edge = s(f.get("edge_id"), 40), pop = s(f.get("pop_id"), 40);
  if (!UUID.test(edge) || (pop && !UUID.test(pop))) return back(req, "/rede/frota?erro=invalido");
  const body: Record<string, unknown> = { name: s(f.get("name"), 60), edge_id: edge, vendor: s(f.get("vendor"), 20) };
  const popName = s(f.get("pop_name"), 60), addr = s(f.get("mgmt_address"), 45), snmp = s(f.get("snmp_version"), 4);
  if (addr && !ADDR.test(addr)) return back(req, "/rede/frota?erro=invalido");   // o endereço digitado nunca volta numa mensagem
  if (pop) body.pop_id = pop;                      // site existente escolhido na lista
  else if (popName) body.pop_name = popName;       // site digitado: a API o encontra pelo nome ou o cria junto com a OLT
  if (addr) body.mgmt_address = addr;
  if (snmp) body.snmp_version = snmp;
  const cred = s(f.get("credential_ref"), 64), label = s(f.get("label"), 80);
  if (cred) body.credential_ref = cred;
  if (label) body.label = label;
  const r = await apiPost("/v1/fleet/olts", JSON.stringify(body), { "Content-Type": "application/json" });
  if (r.status === 201) {
    const id = (r.json as { id?: string } | null)?.id;
    if (f.get("acao") === "credenciais" && id && UUID.test(id)) return back(req, `/rede/frota/${id}?ok=oltcredenciais#credenciais`);   // cadastra e vai direto ao cartão de credenciais (a entrada segura é lá, nunca neste formulário)
    if (f.get("acao") !== "testar" || !id || !UUID.test(id)) return back(req, "/rede/frota?ok=olt");
    // "Cadastrar e testar conexão": o teste é o mesmo do detalhe (leitura da identidade pelo Edge, com orçamento e cache); falhar aqui não desfaz o cadastro
    const t = await apiPost(`/v1/fleet/olts/${id}/connection-test`, undefined, { "Idempotency-Key": `fleet-${randomUUID()}` });
    const o = t.status === 200 ? (t.json as { outcome?: string } | null)?.outcome : null;
    return back(req, `/rede/frota/${id}?ok=${o === "cached" ? "oltcomtestecache" : o ? "oltcomteste" : "oltsemteste"}`);
  }
  const why = r.status === 403 ? (JSON.stringify(r.json ?? {}).includes("feature_disabled") ? "desligado" : "permissao") : r.status === 409 ? "nome" : r.status === 422 ? "invalido"
    : r.status === 404 ? (JSON.stringify(r.json ?? {}).includes("pop") ? "popinexistente" : "edge") : "falha";
  return back(req, `/rede/frota?erro=${why}`);
}
