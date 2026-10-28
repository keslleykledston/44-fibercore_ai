import { cookies } from "next/headers";

export const TOKEN_COOKIE = "fc_token";
export const WS_COOKIE = "fc_ws";
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
