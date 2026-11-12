import { NextResponse, type NextRequest } from "next/server";
import { publicBase } from "@/lib/bff";
import { buildCsp, cspHeaderName, cspMode, generateNonce, safeReportUri } from "@/lib/csp";

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
// O resultado fica 5 s no mapa após a conclusão, para cobrir requisições já em voo com o cookie antigo.
// Restrição de implantação: vale por processo; o web deve rodar com UMA réplica até haver coordenação compartilhada (ADR-0017).
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
    p.finally(() => setTimeout(() => inflight.delete(refresh), 5000)); // a janela de 5 s conta a partir do FIM da chamada
  }
  return p;
}

const isPrefetch = (req: NextRequest) =>
  !!(req.headers.get("next-router-prefetch") || req.headers.get("next-router-segment-prefetch") || req.headers.get("purpose") === "prefetch");

// CSP com nonce por requisição (ADR-0042). O mesmo valor vai (a) no cabeçalho de requisição `Content-Security-Policy[-Report-Only]`, de onde o Next extrai
// o nonce para os próprios scripts, (b) em `x-nonce`, lido pelo layout para o script inline do tema, e (c) no cabeçalho de resposta.
// `FIBERCORE_CSP_MODE`: `report-only` (padrão) | `enforce` | `off`. Lido a cada requisição (não é inlinado no build).
function withCsp(req: NextRequest) {
  const mode = cspMode(process.env.FIBERCORE_CSP_MODE);
  const headers = new Headers(req.headers);
  for (const h of ["content-security-policy", "content-security-policy-report-only", "x-nonce"]) headers.delete(h); // o cliente não injeta política nem nonce para o Next
  if (mode === "off") return { headers, apply: (res: NextResponse) => res };
  const nonce = generateNonce();
  const name = cspHeaderName(mode);
  const policy = buildCsp({ nonce, dev: process.env.NODE_ENV !== "production", reportUri: safeReportUri(process.env.FIBERCORE_CSP_REPORT_URI) });
  headers.set(name, policy);
  headers.set("x-nonce", nonce);
  return { headers, apply: (res: NextResponse) => { res.headers.set(name, policy); return res; } };
}

// A renovação de sessão não roda nas páginas públicas de login (a sessão ainda não existe); o CSP roda em todas as páginas.
const skipsRefresh = (req: NextRequest) => req.nextUrl.pathname.startsWith("/login");

export async function middleware(req: NextRequest) {
  const csp = withCsp(req);
  const next = () => csp.apply(NextResponse.next({ request: { headers: csp.headers } }));
  const refresh = req.cookies.get("fc_refresh")?.value;
  const access = req.cookies.get("fc_token")?.value;
  if ((access && !expiresSoon(access)) || !refresh || isPrefetch(req) || skipsRefresh(req)) return next();
  const body = await rotate(refresh);
  if (body === "unavailable") return next();
  if (!body?.access_token || !body.refresh_token) {
    const res = NextResponse.redirect(new URL("/login", publicBase(req)), 303);
    for (const n of ["fc_token", "fc_refresh", "fc_ws"]) res.cookies.delete(n);
    return csp.apply(res);
  }
  req.cookies.set("fc_token", body.access_token); // visível para a renderização desta mesma requisição
  req.cookies.set("fc_refresh", body.refresh_token);
  // `req.cookies.set` reescreve o cabeçalho `cookie` de `req.headers` (RequestCookies compartilha o Headers); esta cópia leva o valor JÁ RENOVADO
  // (e não o original) para a renderização: provado em e2e (a página protegida renderiza logada na requisição que renovou).
  csp.headers.set("cookie", req.headers.get("cookie") ?? "");
  const res = next();
  res.cookies.set("fc_token", body.access_token, opts(body.expires_in ?? 900));
  res.cookies.set("fc_refresh", body.refresh_token, opts(8 * 3600));
  return res;
}

// Tudo exceto os estáticos do Next, o BFF (JSON/redirecionamentos, sem HTML), os ativos da ajuda e o favicon.
export const config = { matcher: ["/((?!_next/|bff/|ajuda-assets/|favicon).*)"] };
