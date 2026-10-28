import { NextResponse, type NextRequest } from "next/server";
import { publicBase } from "@/lib/bff";

// Renova o access token (cookie de 15 min) com o refresh token rotativo. Só navegações de página: prefetch não consome o refresh,
// porque a API trata reutilização de um refresh já consumido como vazamento e revoga a sessão inteira.
const API = process.env.API_INTERNAL_URL ?? "http://api-core:8000";
const insecure = process.env.FIBERCORE_INSECURE_COOKIES === "1";
const opts = (maxAge: number) => ({ httpOnly: true, secure: !insecure, sameSite: "lax" as const, path: "/", maxAge });

// exp do JWT sem verificar assinatura: só decide QUANDO renovar; quem autentica é a API.
function expiresSoon(jwt: string, skewSeconds = 20): boolean {
  try {
    const payload = JSON.parse(atob(jwt.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return typeof payload.exp !== "number" || payload.exp - Date.now() / 1000 < skewSeconds;
  } catch { return true; }
}

type Rotated = { access_token?: string; refresh_token?: string; expires_in?: number } | null | "unavailable";

// Requisições simultâneas com o mesmo cookie (documento + fetches RSC de uma mesma navegação) compartilham UMA chamada de
// refresh: sem isso a segunda cairia na janela de tolerância da API e a terceira seria lida como roubo (revogando a sessão).
// O resultado fica 5 s no mapa para cobrir requisições já em voo com o cookie antigo.
const inflight = new Map<string, Promise<Rotated>>();

function rotate(refresh: string): Promise<Rotated> {
  let p = inflight.get(refresh);
  if (!p) {
    p = (async (): Promise<Rotated> => {
      try {
        const r = await fetch(`${API}/v1/auth/refresh`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ refresh_token: refresh }), cache: "no-store" });
        if (r.ok) return await r.json();
        return r.status === 401 || r.status === 422 ? null : "unavailable"; // API fora do ar não derruba a sessão
      } catch { return "unavailable"; }
    })();
    inflight.set(refresh, p);
    setTimeout(() => inflight.delete(refresh), 5000);
  }
  return p;
}

const isPrefetch = (req: NextRequest) =>
  !!(req.headers.get("next-router-prefetch") || req.headers.get("next-router-segment-prefetch") || req.headers.get("purpose") === "prefetch");

export async function middleware(req: NextRequest) {
  const refresh = req.cookies.get("fc_refresh")?.value;
  const access = req.cookies.get("fc_token")?.value;
  if ((access && !expiresSoon(access)) || !refresh || isPrefetch(req)) return NextResponse.next();
  const body = await rotate(refresh);
  if (body === "unavailable") return NextResponse.next();
  if (!body?.access_token || !body.refresh_token) {
    const res = NextResponse.redirect(new URL("/login", publicBase(req)), 303);
    for (const n of ["fc_token", "fc_refresh", "fc_ws"]) res.cookies.delete(n);
    return res;
  }
  req.cookies.set("fc_token", body.access_token); // visível para a renderização desta mesma requisição
  req.cookies.set("fc_refresh", body.refresh_token);
  const res = NextResponse.next({ request: { headers: req.headers } });
  res.cookies.set("fc_token", body.access_token, opts(body.expires_in ?? 900));
  res.cookies.set("fc_refresh", body.refresh_token, opts(8 * 3600));
  return res;
}

export const config = { matcher: ["/((?!_next/|bff/|login|ajuda-assets/|favicon).*)"] };
