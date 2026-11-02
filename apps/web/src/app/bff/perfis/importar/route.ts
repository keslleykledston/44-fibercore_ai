import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { parseJson, UUID } from "@/lib/profiles";

const TECH = new Set(["gpon", "epon", "xgspon"]);
const COMPLETE = new Set(["complete", "partial", "unknown"]);
const str = (f: FormData, k: string, max: number) => String(f.get(k) ?? "").trim().slice(0, max);

/** Importa à mão um perfil observado (instantâneo imutável). Nunca fala com a OLT; a origem é SEMPRE `manual_import` (não vale como leitura autoritativa). */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const f = await req.formData();
  const olt = str(f, "olt", 40);
  if (!UUID.test(olt)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const to = (q: string) => `/rede/perfis?olt=${olt}&${q}`;
  const settings = parseJson(str(f, "settings", 20000), "object");
  const technology = str(f, "technology", 10), completeness = str(f, "completeness", 10);
  if (settings === undefined || !TECH.has(technology) || !COMPLETE.has(completeness)) return back(req, to("erro=invalido"));
  const when = str(f, "observed_at", 40);
  const observed = when ? new Date(when) : new Date();
  if (Number.isNaN(observed.getTime())) return back(req, to("erro=invalido"));
  const evidence = str(f, "evidence", 40000);
  const body = {
    native_type: str(f, "native_type", 40), native_key: str(f, "native_key", 80), technology, pon_card: str(f, "pon_card", 60), observed_at: observed.toISOString(), completeness,
    settings, source: "manual_import", ...(evidence ? { evidence } : {}),
  };
  const r = await apiPost(`/v1/olts/${olt}/profiles/import`, JSON.stringify(body), { "Content-Type": "application/json" });
  if (r.status === 201) return back(req, to("ok=importado"));
  const code = r.status === 403 ? "permissao" : r.status === 409 ? "identidade" : r.status === 422 ? "invalido" : "falha";
  return back(req, to(`erro=${code}`));
}
