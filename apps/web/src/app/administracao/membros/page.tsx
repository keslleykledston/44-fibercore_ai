import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { MemberMfaReset } from "@/components/MemberMfaReset";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { roleLabel } from "@/lib/roles";
import type { MemberList } from "@/lib/types";


export default async function Membros() {
  const r = await apiSafe<MemberList>("/v1/members");
  if (r.status === 403) return <AppShell active="/administracao/modulos" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver os membros." /></AppShell>;
  return (
    <AppShell active="/administracao/modulos" user="1">
      <PageHeader title="Membros" subtitle="Quem tem acesso a este workspace e se a verificação em duas etapas está ativa" helpSlug="administracao/membros-e-mfa" />
      <AdminTabs current="/administracao/membros" />
      {r.data === null ? <ErrorState title="Falha ao carregar membros" /> : r.data.members.length === 0 ? <EmptyState title="Nenhum membro" /> : (
        <div className="panel overflow-x-auto" data-testid="members-table">
          <table className="w-full min-w-[560px] text-sm">
            <thead className="text-left text-muted"><tr><th className="p-3 font-medium">Pessoa</th><th className="p-3 font-medium">Perfil</th><th className="p-3 font-medium">MFA</th><th className="p-3 font-medium"><span className="sr-only">Ações</span></th></tr></thead>
            <tbody className="divide-y divide-line">
              {r.data.members.map((m) => (
                <tr key={m.user_id} data-testid={`member-${m.email}`}>
                  <td className="p-3"><div className="font-medium">{m.display_name}{m.is_self ? " (você)" : ""}</div><div className="text-muted">{m.email}</div></td>
                  <td className="p-3">{roleLabel(m.role)}</td>
                  <td className="p-3">{m.mfa_enabled ? <span><span aria-hidden>● </span>Ativo</span> : <span className="text-muted"><span aria-hidden>○ </span>Desativado</span>}</td>
                  <td className="p-3 text-right">{r.data!.can_reset_mfa && !m.is_self && m.mfa_enabled ? <MemberMfaReset userId={m.user_id} name={m.display_name} /> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AppShell>
  );
}
