import { AppShell } from "@/components/AppShell";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import type { Job } from "@/lib/types";

const STATES = ["PREVIEWED", "PENDING_APPROVAL", "APPROVED", "DISPATCHED", "ACCEPTED", "VERIFYING", "SUCCEEDED"];
const label: Record<string, string> = {
  PREVIEWED: "Pré-visualizado", PENDING_APPROVAL: "Aguardando aprovação", APPROVED: "Aprovado", DISPATCHED: "Despachado (não é sucesso)",
  ACCEPTED: "Aceito (não é sucesso)", DEVICE_PENDING: "Pendente no equipamento", VERIFYING: "Verificando", SUCCEEDED: "Sucesso verificado",
  FAILED: "Falhou", EXPIRED: "Expirado", UNKNOWN: "Resultado desconhecido", CANCELLED: "Cancelado",
};
const opName: Record<string, string> = { collect: "Coletar OLT", refresh: "Atualizar CPE", reboot_cpe: "Reiniciar CPE", set_wifi_ssid: "Alterar Wi-Fi", provision_onu: "Provisionar ONU" };

export default async function Operacoes() {
  const r = await apiSafe<Job[]>("/v1/jobs?limit=50");
  if (r.status === 403) return <AppShell active="/operacoes" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver operações." /></AppShell>;
  const list = r.data ?? [];
  return (
    <AppShell active="/operacoes" user="1">
      <PageHeader title="Operações" subtitle="Solicitações e aprovações; escrita em rede está bloqueada nesta fase" helpSlug="operacoes/acompanhar-operacoes" />
      <p className="panel mb-4 p-4 text-sm" data-testid="write-blocked">Operações que alteram equipamentos (reiniciar, Wi-Fi, provisionar) ficam <strong>bloqueadas</strong>: “Operação não homologada”. Apenas leituras (coletar/atualizar) são executadas.</p>
      {r.data === null ? <ErrorState title="Falha ao carregar operações" /> : list.length === 0 ? <EmptyState title="Nenhuma operação" /> : (
        <div className="panel overflow-x-auto" data-testid="jobs-table">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-left text-muted"><tr><th className="p-3 font-medium">Operação</th><th className="p-3 font-medium">Risco</th><th className="p-3 font-medium">Estado</th><th className="p-3 font-medium">Aprovações</th><th className="p-3 font-medium">Ação</th></tr></thead>
            <tbody className="divide-y divide-line">
              {list.map((j) => (
                <tr key={j.id}>
                  <td className="p-3 font-medium">{opName[j.operation] ?? j.operation}</td>
                  <td className="p-3">{j.risk}</td>
                  <td className="p-3">
                    {label[j.status] ?? j.status}
                    {STATES.includes(j.status) && <div className="text-xs text-muted" aria-label="Linha do tempo">{STATES.map((s) => (s === j.status ? `[${label[s]?.split(" (")[0]}]` : "·")).join(" ")}</div>}
                  </td>
                  <td className="p-3">{j.required_approvals === 0 ? "não exige" : `${j.required_approvals} distinta(s)`}</td>
                  <td className="p-3">{j.blocked_reason ? <button disabled aria-disabled className="min-h-touch rounded-btn border border-line px-3 text-muted" title="Operação não homologada">Bloqueada: operação não homologada</button> : <span className="text-muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AppShell>
  );
}
