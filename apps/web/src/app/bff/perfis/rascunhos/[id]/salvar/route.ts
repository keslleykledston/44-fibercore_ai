import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { LIST_FIELDS, parseJson, SCALAR_NUM, SHAPING, TAGGING, UUID } from "@/lib/profiles";

const str = (f: FormData, k: string, max: number) => String(f.get(k) ?? "").trim().slice(0, max);

/** Salva o rascunho (PATCH com If-Match): 412 = outra pessoa salvou antes, a tela mostra o aviso e não sobrescreve. Modo `form` monta o objeto tipado campo a campo; `json` aceita o objeto inteiro. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const f = await req.formData();
  const to = (q: string) => `/rede/perfis/${id}?${q}`;
  const version = str(f, "version", 10);
  if (!/^[0-9]{1,9}$/.test(version)) return back(req, to("erro=invalido"));
  const mode = str(f, "mode", 4);
  let desired: unknown;
  if (mode === "json") {
    desired = parseJson(str(f, "desired_json", 20000), "object");
  } else {
    const d: Record<string, unknown> = {};
    for (const k of SCALAR_NUM) { const v = str(f, k, 12); if (v !== "") d[k] = /^[0-9]{1,11}$/.test(v) ? Number(v) : NaN; }
    const dba = str(f, "dba_type", 64); if (dba) d.dba_type = dba;
    const tag = str(f, "tagging", 12); if (tag) d.tagging = (TAGGING as readonly string[]).includes(tag) ? tag : null;
    const sh = str(f, "shaping_owner", 8); if (sh) d.shaping_owner = (SHAPING as readonly string[]).includes(sh) ? sh : null;
    const mc = str(f, "multicast", 5); if (mc === "true" || mc === "false") d.multicast = mc === "true";
    const desc = str(f, "description", 256); if (desc) d.description = desc;
    for (const k of LIST_FIELDS) { const raw = str(f, k, 8000); if (raw) d[k] = parseJson(raw, "array"); }
    desired = d;
  }
  if (desired === undefined || Object.values(desired as Record<string, unknown>).some((v) => v === undefined || v === null || (typeof v === "number" && Number.isNaN(v)))) return back(req, to("erro=invalido"));
  const body: Record<string, unknown> = { desired };
  const name = str(f, "name", 80), reason = str(f, "reason", 300);
  if (name) body.name = name;
  if (reason) body.reason = reason;
  const r = await apiPost(`/v1/profile-drafts/${id}`, JSON.stringify(body), { "Content-Type": "application/json", "If-Match": `"${version}"` }, "PATCH");
  if (r.status === 200) return back(req, to("ok=salvo"));
  return back(req, to(`erro=${r.status === 412 ? "versao" : r.status === 403 ? "permissao" : r.status === 422 ? "invalido" : "falha"}`));
}
