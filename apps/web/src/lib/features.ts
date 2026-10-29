import "server-only";
import { apiSafe } from "./api";
import type { TenantFeature } from "./types";

/** Flags por provedor (ADR-0023): TODAS as nomeadas precisam estar ligadas. Falha ao consultar = desligada: nunca liga uma tela por engano. */
export async function featuresOn(...names: string[]): Promise<boolean> {
  const r = await apiSafe<TenantFeature[]>("/v1/tenant/features");
  return names.every((n) => !!r.data?.find((f) => f.feature === n)?.enabled);
}

/** A Visão 360 mostra dados da rota de contexto do cliente (customer_context): sem ela a tela só daria 403. */
export const subscriber360On = () => featuresOn("subscriber_360", "customer_context");

/** O diagnóstico guiado parte da Visão 360 e executa a regra: precisa das três flags. */
export const diagnosticsOn = () => featuresOn("subscriber_360", "customer_context", "diagnostic_engine");

