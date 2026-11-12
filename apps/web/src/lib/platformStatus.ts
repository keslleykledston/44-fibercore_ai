import "server-only";
import { cache } from "react";
import { apiSafe } from "./api";
import type { PlatformStatus } from "./platform";

/** A conta logada é operadora da plataforma? (e o segundo fator está recente?) Só a PRÓPRIA conta; decide só o menu e o passo do segundo fator: as rotas da API conferem de novo e respondem 403 a qualquer outra.
 *  Falha ao consultar = não operadora: nunca mostra o item por engano. Uma consulta por requisição (React cache). */
export const platformStatus = cache(async (): Promise<PlatformStatus> => {
  try {
    const r = await apiSafe<PlatformStatus>("/v1/platform/status");
    return r.data ?? { operator: false, mfa_recent: false };
  } catch (e) {
    if (String((e as { digest?: unknown })?.digest ?? "").startsWith("NEXT_REDIRECT")) throw e;   // sessão vencida: segue o redirecionamento ao login
    return { operator: false, mfa_recent: false };
  }
});
