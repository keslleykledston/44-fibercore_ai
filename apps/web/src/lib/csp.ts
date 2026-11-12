// Content-Security-Policy com nonce por requisição (ADR-0042). Funções PURAS: sem Next, sem I/O, testáveis em Node.
// Quem emite o cabeçalho é o middleware (src/middleware.ts); o layout lê o nonce em `x-nonce` para o único script inline do app.

/** Modo de aplicação. `report-only` (padrão) só relata no console; `enforce` bloqueia; `off` não emite nada (rollback sem rebuild). */
export type CspMode = "report-only" | "enforce" | "off";

export const CSP_ENFORCE_HEADER = "Content-Security-Policy";
export const CSP_REPORT_ONLY_HEADER = "Content-Security-Policy-Report-Only";

/** `FIBERCORE_CSP_MODE`: ausente ou desconhecido = `report-only` (falha para o lado que não quebra a LAB). */
export function cspMode(raw: string | undefined | null): CspMode {
  const v = (raw ?? "").trim().toLowerCase();
  if (v === "enforce" || v === "off") return v;
  return "report-only";
}

export function cspHeaderName(mode: Exclude<CspMode, "off">): string {
  return mode === "enforce" ? CSP_ENFORCE_HEADER : CSP_REPORT_ONLY_HEADER;
}

/** Nonce de 128 bits (CSP exige >= 128 bits imprevisíveis), base64 padrão. `random` é injetável só para teste. */
export function generateNonce(random: (n: Uint8Array) => Uint8Array = (n) => crypto.getRandomValues(n)): string {
  const bytes = random(new Uint8Array(16));
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

const NONCE_RE = /^[A-Za-z0-9+/]{22}={0,2}$/;

/** `FIBERCORE_CSP_REPORT_URI`: caminho absoluto no mesmo host ("/csp-report") ou URL https, sem espaço, `;` ou `,` (não pode injetar diretiva). */
export function safeReportUri(raw: string | undefined | null): string | null {
  const v = (raw ?? "").trim();
  if (!v || /[\s;,'"]/.test(v)) return null;
  return /^\/(?!\/)[A-Za-z0-9._~\-/]*$/.test(v) || /^https:\/\/[A-Za-z0-9.-]+(:\d+)?(\/[A-Za-z0-9._~\-/]*)?$/.test(v) ? v : null;
}

export type CspOptions = { nonce: string; dev?: boolean; reportUri?: string | null };

/**
 * A política. O que sobra de `'unsafe-inline'` é UM item, deliberado e medido (ADR-0042 §Estilo): `style-src-attr` (atributos `style="…"` renderizados
 * no servidor pelos componentes de régua óptica e de LEDs). Nonce não vale para atributo; o risco é só CSS (nenhuma execução de script).
 * Scripts: sem `'unsafe-inline'` e sem `'unsafe-eval'` em produção. `'strict-dynamic'` faz o navegador ignorar `'self'` (só o nonce e o que ele carrega
 * valem); `'self'` fica de reserva para navegadores sem CSP3.
 */
export function buildCsp({ nonce, dev = false, reportUri = null }: CspOptions): string {
  if (!NONCE_RE.test(nonce)) throw new Error("nonce inválido: esperado base64 de 16 bytes");
  const d = [
    ["default-src", "'self'"],
    ["script-src", `'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`],   // dev: o React usa eval para reconstruir pilhas; nunca em produção
    ["style-src", `'self' 'nonce-${nonce}'`],
    ["style-src-attr", "'unsafe-inline'"],
    ["img-src", "'self' data:"],            // data: = QR do MFA (qrcode.toDataURL); as demais imagens são do próprio host
    ["font-src", "'self'"],
    ["connect-src", dev ? "'self' ws: wss:" : "'self'"],   // dev: HMR do Next por websocket
    ["object-src", "'none'"],
    ["base-uri", "'self'"],
    ["frame-ancestors", "'none'"],
    ["form-action", "'self'"],
  ];
  if (reportUri) d.push(["report-uri", reportUri]);
  return d.map(([k, v]) => `${k} ${v}`).join("; ");
}
