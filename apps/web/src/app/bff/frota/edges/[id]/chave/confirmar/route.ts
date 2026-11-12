import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { UUID } from "@/lib/fleet";

const KEY_ID = /^[0-9a-f]{16}$/;

/** Confirma a chave do Edge: a pessoa digita a impressão digital que o servidor do Edge mostra (`fibercore-edge seal-fingerprint`) e a API compara com a da chave vigente. O valor digitado nunca volta numa mensagem. */
export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id } = await params;
  if (!UUID.test(id)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const f = await req.formData();
  const olt = String(f.get("olt") ?? ""), keyId = String(f.get("key_id") ?? ""), fp = String(f.get("fingerprint") ?? "").trim().slice(0, 64);
  if (!UUID.test(olt)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const to = (q: string) => `/rede/frota/${olt}?${q}#credenciais`;
  if (!KEY_ID.test(keyId) || !fp) return back(req, to("erro=impressao"));
  const r = await apiPost(`/v1/fleet/edges/${id}/seal-key/confirm`, JSON.stringify({ key_id: keyId, fingerprint: fp }), { "Content-Type": "application/json" });
  if (r.status === 200) return back(req, to("ok=chaveconfirmada"));
  const txt = JSON.stringify(r.json ?? {});
  if (r.status === 403) return back(req, to(`erro=${txt.includes("feature_disabled") ? "desligado" : "permissao"}`));
  if (r.status === 422) return back(req, to("erro=impressao"));
  if (r.status === 409) return back(req, to(`erro=${txt.includes("no_seal_key") ? "semchave" : "chavemudou"}`));
  return back(req, to("erro=falha"));
}
