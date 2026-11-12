import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";
import { cookieOpts } from "@/lib/session";
import { type CreatedOrg, FLASH_COOKIE, FLASH_PATH, FLASH_SECONDS, encodeFlash, orgError } from "@/lib/platform";

const s = (v: FormDataEntryValue | null, max: number) => String(v ?? "").trim().slice(0, max);

/** Nova organização (ADR-0046 D1), sem JavaScript: formulário → API → redirecionamento. O link do convite NUNCA vai na URL: vai num cookie HttpOnly de 2 minutos preso a /plataforma. */
export async function POST(req: Request) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const f = await req.formData();
  const name = s(f.get("name"), 200);
  const body: Record<string, unknown> = { name, admin_email: s(f.get("admin_email"), 320) };
  const adminName = s(f.get("admin_name"), 200);
  if (adminName) body.admin_name = adminName;
  const r = await apiPost("/v1/platform/organizations", JSON.stringify(body), { "Content-Type": "application/json" });
  if (r.status === 401) return back(req, "/login");
  if (r.status === 201) {
    const res = back(req, "/plataforma/organizacoes?ok=criada");
    res.cookies.set(FLASH_COOKIE, encodeFlash(r.json as CreatedOrg), { ...cookieOpts(FLASH_SECONDS), path: FLASH_PATH, sameSite: "strict" });
    return res;
  }
  // só o nome volta na URL (para não redigitar); o e-mail do administrador nunca
  return back(req, `/plataforma/organizacoes?erro=${orgError(r.status, r.json)}${name ? `&nome=${encodeURIComponent(name.slice(0, 60))}` : ""}`);
}

export const dynamic = "force-dynamic";
