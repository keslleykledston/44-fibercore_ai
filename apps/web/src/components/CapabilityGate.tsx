import { StatusPill } from "@/components/ui";
import type { Capability } from "@/lib/types";

const LABEL: Record<string, string> = { collect: "Coleta de inventário", provision_onu: "Provisionar ONU", refresh: "Atualizar leitura", reboot_cpe: "Reiniciar CPE", set_wifi_ssid: "Alterar nome do Wi-Fi" };
const STATUS: Record<string, string> = { supported: "Suportada", unsupported: "Não suportada", unknown: "Desconhecida" };
const REASON: Record<string, string> = { operation_not_homologated: "Bloqueada: operação ainda não homologada" };

/** Capacidades de um perfil (vendor/modelo/firmware). Sem registro = Desconhecida: ausência de evidência nunca é suporte. */
export function CapabilityGate({ caps, title }: { caps: Capability[]; title: string }) {
  const p = caps[0];
  const profile = p && p.vendor && p.model && p.firmware ? `${p.vendor} ${p.model} · ${p.firmware}` : null;
  return (
    <div className="mt-4 border-t border-line pt-3" data-testid="capability-gate">
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-1 text-xs text-muted">{profile ? `Perfil: ${profile}` : "Perfil incompleto (fabricante, modelo ou firmware não informado): nada pode ser confirmado."}</p>
      <ul className="mt-2 divide-y divide-line text-sm">
        {caps.map((c) => (
          <li key={`${c.protocol}-${c.name}`} className="flex flex-wrap items-center justify-between gap-2 py-2" data-testid={`cap-${c.name}`}>
            <span>{LABEL[c.name] ?? c.name} <span className="text-xs text-muted">· {c.writes ? "escrita" : "leitura"} · {c.protocol}</span></span>
            <span className="flex flex-wrap items-center gap-2"><span>{STATUS[c.status]}</span><StatusPill value={c.certification} /></span>
            {c.blocked_reason && <span className="w-full text-xs text-warn">{REASON[c.blocked_reason] ?? c.blocked_reason}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
