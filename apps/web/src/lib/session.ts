import { cookies } from "next/headers";

export const TOKEN_COOKIE = "fc_token";
export const WS_COOKIE = "fc_ws";
export const REFRESH_COOKIE = "fc_refresh";
export const MFA_COOKIE = "fc_mfa"; // desafio de MFA (5 min), só existe entre a senha e o código
export const cookieOpts = (maxAge: number) => ({
  httpOnly: true,
  // Secure exceto em HTTP de loopback (dev/E2E). Em produção o proxy serve HTTPS.
  secure: process.env.FIBERCORE_INSECURE_COOKIES !== "1",
  sameSite: "lax" as const,
  path: "/",
  maxAge,
});

export async function getSession() {
  const jar = await cookies();
  return { token: jar.get(TOKEN_COOKIE)?.value ?? null, workspace: jar.get(WS_COOKIE)?.value ?? null };
}

export const REFRESH_MAX_AGE = 8 * 3600; // mesma janela do refresh token da API

type CookieJar = { set: (name: string, value: string, opts: ReturnType<typeof cookieOpts>) => unknown; delete: (name: string) => unknown };

export function setSessionCookies(jar: CookieJar, access: string, refresh: string, expiresIn: number) {
  jar.set(TOKEN_COOKIE, access, cookieOpts(expiresIn)); // mesmo TTL do token da API
  jar.set(REFRESH_COOKIE, refresh, cookieOpts(REFRESH_MAX_AGE));
  jar.delete(MFA_COOKIE);
}

export function clearSessionCookies(jar: CookieJar) {
  for (const n of [TOKEN_COOKIE, REFRESH_COOKIE, WS_COOKIE, MFA_COOKIE]) jar.delete(n);
}
