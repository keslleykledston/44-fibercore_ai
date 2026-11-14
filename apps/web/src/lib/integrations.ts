// Tokens de API e webhooks (ADR-0051): textos e regras PURAS da tela. Sem acesso à rede: o servidor confere tudo de novo.

export const PERMISSION_LABEL: Record<string, { label: string; hint: string }> = {
  "inventory:read": { label: "Ver a rede", hint: "OLTs, ONUs, PONs e CPEs." },
  "incidents:read": { label: "Ver incidentes", hint: "Incidentes abertos e resolvidos." },
  "fleet:read": { label: "Ver a frota de OLTs", hint: "OLTs cadastradas, sites e testes de conexão." },
  "discovery:read": { label: "Ver ONUs aguardando autorização", hint: "Fila de ONUs ainda não autorizadas (só leitura)." },
  "diagnostics:quality_read": { label: "Ver qualidade do serviço", hint: "Leituras de qualidade e histórico (só leitura)." },
};

export const EVENT_LABEL: Record<string, string> = {
  "incident.opened": "Incidente aberto",
  "incident.resolved": "Incidente resolvido",
  "webhook.test": "Teste de entrega",
};

export const STATE_LABEL: Record<string, string> = { active: "Ativo", revoked: "Revogado", expired: "Vencido", sent: "Entregue", failed: "Falhou", pending: "Na fila" };

export const DELIVERY_ERROR: Record<string, string> = {
  http_error: "o servidor respondeu com erro", redirect_not_followed: "respondeu com redirecionamento (não seguimos)", dns_failed: "o nome não foi encontrado",
  address_not_public: "o endereço não é público (bloqueado por segurança)", tls_failed: "falha no certificado/TLS", timeout: "não respondeu a tempo", connection_failed: "não conseguiu conectar",
  body_too_large: "mensagem grande demais", secret_unreadable: "segredo ilegível", expired: "venceu sem ser entregue",
};

export const DISABLED_REASON: Record<string, string> = { too_many_failures: "desligado após 10 falhas seguidas" };

export const MAX_TOKEN_DAYS = 365;
export const clampDays = (n: number, max = MAX_TOKEN_DAYS) => (Number.isFinite(n) ? Math.min(max, Math.max(1, Math.trunc(n))) : 90);

/** Só confere a forma (https, nome em vez de IP); a API decide. Devolve o código de erro ou null. */
export function urlProblem(raw: string): string | null {
  let u: URL;
  try { u = new URL(raw); } catch { return "url_invalid"; }
  if (u.protocol !== "https:") return "url_must_be_https";
  if (u.username || u.password) return "url_invalid";
  const h = u.hostname;
  if (/^\d+\.\d+\.\d+\.\d+$/.test(h) || h.startsWith("[")) return "url_host_must_be_a_name";
  if (!h.includes(".") || h === "localhost" || /\.(local|internal|localhost)$/.test(h)) return "url_host_not_public";
  return null;
}

/** O exemplo de conferência da assinatura (o mesmo de docs/operations/INTEGRACOES_TOKENS_E_WEBHOOKS.md). */
export const SIGNATURE_EXAMPLE = `import hmac, hashlib, time
def valido(segredo: str, cabecalho: str, corpo: bytes, tolerancia=300) -> bool:
    p = dict(x.split("=", 1) for x in cabecalho.split(","))
    if abs(time.time() - int(p["t"])) > tolerancia:
        return False
    esperado = hmac.new(segredo.encode(), p["t"].encode() + b"." + corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, p["v1"])`;

export const failureText = (code: string | null | undefined) => (code ? (DELIVERY_ERROR[code] ?? "falha na entrega") : null);
