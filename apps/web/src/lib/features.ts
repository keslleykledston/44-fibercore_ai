import "server-only";
import { apiSafe } from "./api";
import type { TenantFeature } from "./types";

/** Flag por provedor (ADR-0023). Falha ao consultar = desligada: nunca liga uma tela por engano. */
export async function featureOn(name: string): Promise<boolean> {
  const r = await apiSafe<TenantFeature[]>("/v1/tenant/features");
  return !!r.data?.find((f) => f.feature === name)?.enabled;
}
