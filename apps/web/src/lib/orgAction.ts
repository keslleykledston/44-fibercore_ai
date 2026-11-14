import "server-only";
import { apiPost } from "./api";
import { back } from "./bff";
import { orgError, UUID_FORMAT } from "./platform";

/** Texto de formulário: aparado e com teto (o servidor valida de novo). */
export const field = (v: FormDataEntryValue | null, max: number) => String(v ?? "").trim().slice(0, max);

/**
 * Uma mudança do operador sem JavaScript (ADR-0047): formulário → API → redirecionamento ao detalhe com `ok` ou `erro` (códigos curtos; nunca texto da API).
 * `changed:false` vira o aviso "nada mudou". 401 → login. Id fora do formato UUID: volta à lista sem chamar a API.
 */
export async function orgAction(req: Request, id: string, path: string, method: "POST" | "PUT", payload: Record<string, unknown>, okCode: string) {
  if (!UUID_FORMAT.test(id)) return back(req, "/plataforma/organizacoes?erro=naoencontrada");
  const r = await apiPost(`/v1/platform/organizations/${id}${path}`, JSON.stringify(payload), { "Content-Type": "application/json" }, method);
  if (r.status === 401) return back(req, "/login");
  const to = `/plataforma/organizacoes/${id}`;
  if (r.status === 200 || r.status === 201) return back(req, `${to}?ok=${(r.json as { changed?: boolean } | null)?.changed === false ? "semmudanca" : okCode}`);
  return back(req, `${to}?erro=${orgError(r.status, r.json)}`);
}
