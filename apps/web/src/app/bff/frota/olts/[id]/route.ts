import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/fleet";
import { hostKeyProblem, portProblem } from "@/lib/oltConnection";

const ADDR = /^[0-9A-Fa-f:.]{2,45}$/;
const s = (v: FormDataEntryValue | null, max: number) => String(v ?? "").trim().slice(0, max);

/** Edita o site (POP), o rótulo, o endereço de gerência, a versão do SNMP, como a OLT é alcançada (protocolo, porta, transporte, impressão digital...) e o NOME da credencial de uma OLT. POP e rótulo vazios limpam; a credencial só muda por substituição ou remoção explícita. Nada é enviado à OLT. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const f = await req.formData();
  const pop = s(f.get("pop_id"), 40), popName = s(f.get("pop_name"), 60), addr = s(f.get("mgmt_address"), 45), snmp = s(f.get("snmp_version"), 4);
  if (pop && !UUID.test(pop)) return back(req, `/rede/frota/${id}?erro=invalido`);
  if (addr && !ADDR.test(addr)) return back(req, `/rede/frota/${id}?erro=invalido`);   // o endereço digitado nunca volta numa mensagem
  const body: Record<string, unknown> = { label: s(f.get("label"), 80) || null, snmp_version: snmp || null };
  if (pop) body.pop_id = pop;                       // site existente
  else if (popName) body.pop_name = popName;        // site digitado: encontrado pelo nome ou criado
  else body.pop_id = null;                          // campo vazio limpa o site
  // ADR-0046: como a OLT é alcançada. A porta só vai se mudou em relação ao que a OLT tinha (assim trocar o protocolo usa a porta padrão do novo). Telnet não leva impressão digital, modo SSH nem SSH legado.
  if (f.has("mgmt_protocol")) {
    const proto = s(f.get("mgmt_protocol"), 8);
    if (proto && proto !== "ssh" && proto !== "telnet") return back(req, `/rede/frota/${id}?erro=invalido`);
    body.mgmt_protocol = proto || null;
    const port = s(f.get("mgmt_port"), 5), original = s(f.get("mgmt_port_original"), 5);
    if (proto && port && port !== original) { if (portProblem(port)) return back(req, `/rede/frota/${id}?erro=porta`); body.mgmt_port = Number(port); }
    if (proto === "ssh") {
      const sp = s(f.get("snmp_port"), 5), hk = s(f.get("host_key_sha256"), 64);
      if (sp && portProblem(sp)) return back(req, `/rede/frota/${id}?erro=porta`);
      if (hk && hostKeyProblem(hk)) return back(req, `/rede/frota/${id}?erro=impressaodigital`);
      body.mgmt_transport = s(f.get("mgmt_transport"), 4) || "cli";
      body.snmp_port = sp ? Number(sp) : null;
      body.host_key_sha256 = hk || null;
      body.ssh_mode = s(f.get("ssh_mode"), 5) || "exec";
      body.legacy_ssh = f.get("legacy_ssh") === "1";
    }
  }
  // o endereço salvo nunca volta da API: vazio mantém, digitar substitui, a caixa remove
  if (f.get("remover_endereco") === "1") body.mgmt_address = null;
  else if (addr) body.mgmt_address = addr;
  // o nome da credencial nunca volta da API: o campo vem vazio e só muda quando a pessoa SUBSTITUI (digitando) ou REMOVE (caixa); campo vazio sem a caixa não toca na credencial
  const cred = s(f.get("credential_ref"), 64);
  if (f.get("remover_credencial") === "1") body.credential_ref = null;
  else if (cred) body.credential_ref = cred;
  const r = await apiPost(`/v1/fleet/olts/${id}`, JSON.stringify(body), { "Content-Type": "application/json" }, "PATCH");
  if (r.status === 200) return back(req, `/rede/frota/${id}?ok=oltatualizada`);
  const detail = (r.json as { detail?: unknown } | null)?.detail;
  const why422 = detail === "protocol_required" || detail === "telnet_has_no_ssh_fields" ? "protocolo" : detail === "snmp_transport_needs_v2c" ? "snmpv2" : "invalido";
  if (r.status === 409 && detail === "delivery_in_flight") return back(req, `/rede/frota/${id}?erro=emandamento`);   // o Edge ainda aplica uma entrega desta OLT
  return back(req, `/rede/frota/${id}?erro=${r.status === 403 ? "permissao" : r.status === 422 ? why422 : r.status === 404 ? "popinexistente" : "falha"}`);
}
