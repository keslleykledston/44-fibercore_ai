import { AppShell } from "@/components/AppShell";
import { DevicesTabs } from "@/components/DevicesTabs";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import type { Capability, Cpe, Olt } from "@/lib/types";

const OP: Record<string, string> = { collect: "Coleta de inventário", refresh: "Atualizar leitura", reboot_cpe: "Reiniciar CPE", set_wifi_ssid: "Alterar nome do Wi-Fi", provision_onu: "Provisionar ONU", onu_reset: "Reiniciar ONU na OLT", onu_deactivate: "Desativar ONU na OLT" };
const CERT: Record<string, string> = { identified: "Identificado", observed: "Observado", certified: "Certificado" };
const MAX_PROFILES = 40;
const CPE_LIMIT = 1000, OLT_LIMIT = 200; // limites das listas da API: bateu no limite, a matriz pode não cobrir todos os perfis

type Profile = { kind: "cpe" | "olt"; vendor: string | null; model: string | null; firmware: string | null; id: string; count: number };

function profiles(cpes: Cpe[], olts: Olt[]): Profile[] {
  const m = new Map<string, Profile>();
  const add = (kind: "cpe" | "olt", id: string, v: string | null, mo: string | null, fw: string | null) => {
    const k = `${kind}|${v}|${mo}|${fw}`;
    const p = m.get(k);
    if (p) p.count++; else m.set(k, { kind, vendor: v, model: mo, firmware: fw, id, count: 1 });
  };
  cpes.forEach((c) => add("cpe", c.id, c.vendor, c.model, c.firmware));
  olts.forEach((o) => add("olt", o.id, o.vendor, o.model, o.firmware));
  return [...m.values()].sort((a, b) => a.kind.localeCompare(b.kind) || `${a.vendor}${a.model}`.localeCompare(`${b.vendor}${b.model}`, "pt-BR"));
}

export default async function Capacidades() {
  const [cpes, olts] = await Promise.all([apiSafe<Cpe[]>(`/v1/cpes?limit=${CPE_LIMIT}`), apiSafe<Olt[]>(`/v1/olts?limit=${OLT_LIMIT}`)]);
  if (cpes.status === 403 || olts.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
  const all = profiles(cpes.data ?? [], olts.data ?? []);
  const shown = all.slice(0, MAX_PROFILES);
  const rows = await Promise.all(shown.map(async (p) => ({ p, caps: await apiSafe<Capability[]>(`/v1/${p.kind === "cpe" ? "cpes" : "olts"}/${p.id}/capabilities`) })));
  const gaps = [
    cpes.data === null ? "A lista de CPEs não carregou: os perfis de CPE não aparecem." : cpes.data.length >= CPE_LIMIT ? `A lista de CPEs foi limitada a ${CPE_LIMIT}: pode haver perfis de CPE que não aparecem.` : null,
    olts.data === null ? "A lista de OLTs não carregou: os perfis de OLT não aparecem." : olts.data.length >= OLT_LIMIT ? `A lista de OLTs foi limitada a ${OLT_LIMIT}: pode haver perfis de OLT que não aparecem.` : null,
  ].filter((x): x is string => x !== null);
  const ops = [...new Set(rows.flatMap((r) => (r.caps.data ?? []).map((c) => c.name)))];
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Capacidades" subtitle="O que cada modelo e firmware tem comprovado, por operação (somente leitura)" helpSlug="rede/capacidades" />
      <DevicesTabs current="/dispositivos/capacidades" />
      {cpes.data === null && olts.data === null ? <ErrorState title="Falha ao carregar o inventário" /> : rows.length === 0 && gaps.length === 0 ? <EmptyState title="Nenhum dispositivo coletado" /> : (
        <div data-testid="capabilities-ready">
          {gaps.length > 0 && <div role="status" data-testid="capabilities-incomplete" className="panel mb-4 border-warn p-4 text-sm text-warn"><strong>Matriz incompleta.</strong> {gaps.join(" ")}</div>}
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <caption className="sr-only">Capacidades por perfil de dispositivo</caption>
              <thead className="text-left text-muted"><tr>
                <th scope="col" className="p-3 font-medium">Perfil</th>
                {ops.map((o) => <th key={o} scope="col" className="p-3 font-medium">{OP[o] ?? o}</th>)}
              </tr></thead>
              <tbody className="divide-y divide-line">
                {rows.map(({ p, caps }) => (
                  <tr key={`${p.kind}-${p.vendor}-${p.model}-${p.firmware}`}>
                    <th scope="row" className="p-3 text-left font-normal">
                      <div className="font-medium">{p.vendor ?? "—"} · {p.model ?? "—"}</div>
                      <div className="text-xs text-muted">{p.kind === "olt" ? "OLT" : "CPE"} · {p.firmware ?? "firmware não informado"} · {p.count} no inventário</div>
                    </th>
                    {caps.data === null ? (
                      <td colSpan={Math.max(1, ops.length)} className="p-3 text-warn" data-testid="caps-unavailable">
                        {caps.status === 403 ? "Registro de capacidades desligado ou sem permissão para este provedor." : "Não foi possível carregar as capacidades deste perfil."} Isso não significa que não há suporte.
                      </td>
                    ) : ops.map((o) => {
                      const c = caps.data?.find((x) => x.name === o);
                      if (!c) return <td key={o} className="p-3 text-muted">—</td>;
                      return (
                        <td key={o} className="p-3" data-testid={`cell-${o}`}>
                          <div>{c.status === "supported" ? "Suportada" : c.status === "unsupported" ? "Não suportada" : "Desconhecida"}</div>
                          <div className="text-xs text-muted">{CERT[c.certification] ?? c.certification} · {c.writes ? "escrita" : "leitura"}</div>
                          {c.blocked_reason && <div className="text-xs text-warn">Bloqueada: não homologada</div>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {all.length > MAX_PROFILES && <p className="mt-3 text-xs text-warn">Mostrando {MAX_PROFILES} de {all.length} perfis.</p>}
          <p className="mt-3 text-xs text-muted">Ausência de registro é “Desconhecida”: nunca é lida como suporte. Escrita só vale para o que está Observado ou Certificado para o alvo, e continua bloqueada fora da bancada.</p>
        </div>
      )}
    </AppShell>
  );
}
