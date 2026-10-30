import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { MemberRoleChange } from "@/components/MemberRoleChange";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { RISK, roleLabel } from "@/lib/roles";
import type { MeInfo, MemberList, PermissionInfo, RoleHistory, RoleList } from "@/lib/types";

const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" });
const who = (p: { name: string | null; email: string | null; id: string | null }) => p.name ?? (p.id ? `conta ${p.id.slice(0, 8)}… (já não é membro)` : "—");

export default async function Papeis() {
  const [me, roles, members, history] = await Promise.all([
    apiSafe<MeInfo>("/v1/auth/me"), apiSafe<RoleList>("/v1/roles"), apiSafe<MemberList>("/v1/members"), apiSafe<RoleHistory>("/v1/members/role-history?limit=50"),
  ]);
  const mine = me.data?.permissions ?? [];
  const byRisk = (["R3", "R2", "R1", "R0"] as const).map((k) => [k, mine.filter((p) => p.risk === k)] as const).filter(([, l]) => l.length > 0);
  const assignable = (roles.data?.roles ?? []).filter((r) => r.assignable_by_me).map((r) => r.role);
  const allPerms: PermissionInfo[] = [];
  for (const r of roles.data?.roles ?? []) for (const p of r.permissions) if (!allPerms.some((x) => x.name === p.name)) allPerms.push(p);
  allPerms.sort((a, b) => b.risk.localeCompare(a.risk) || a.name.localeCompare(b.name));
  return (
    <AppShell active="/administracao/modulos" user="1">
      <PageHeader title="Papéis e permissões" subtitle="O que cada papel pode fazer, quem tem qual papel e como isso mudou" helpSlug="administracao/papeis-e-permissoes" />
      <AdminTabs current="/administracao/papeis" />
      <div data-testid="roles-ready" className="grid gap-6">
        <section aria-labelledby="h-mine" className="panel p-4">
          <h2 id="h-mine" className="text-sm font-semibold uppercase tracking-wide text-muted">O que eu posso fazer</h2>
          {me.data === null ? <p className="mt-2 text-sm text-danger">Não foi possível carregar o seu papel.</p> : (
            <>
              <p className="mt-2 text-sm" data-testid="my-role">Seu papel neste workspace: <strong>{roleLabel(me.data.role)}</strong></p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                {byRisk.map(([k, list]) => (
                  <div key={k}>
                    <h3 className="text-sm font-medium">{RISK[k].label} <span className="text-xs text-muted">· {RISK[k].hint}</span></h3>
                    <ul className="mt-1 list-disc pl-5 text-sm text-muted">{list.map((p) => <li key={p.name}><span className="text-text">{p.description}</span> <code className="text-xs">{p.name}</code></li>)}</ul>
                  </div>
                ))}
              </div>
            </>
          )}
        </section>

        <section aria-labelledby="h-members">
          <h2 id="h-members" className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Membros e papéis</h2>
          {members.status === 403 ? <p className="panel p-4 text-sm text-muted">Seu papel não permite ver os membros.</p> : members.data === null ? <ErrorState title="Falha ao carregar membros" /> : members.data.members.length === 0 ? <EmptyState title="Nenhum membro" /> : (
            <div className="panel overflow-x-auto" data-testid="role-members">
              <table className="w-full min-w-[560px] text-sm">
                <caption className="sr-only">Membros do workspace e seus papéis</caption>
                <thead className="text-left text-muted"><tr><th scope="col" className="p-3 font-medium">Pessoa</th><th scope="col" className="p-3 font-medium">Papel</th><th scope="col" className="p-3 font-medium"><span className="sr-only">Ação</span></th></tr></thead>
                <tbody className="divide-y divide-line">
                  {members.data.members.map((m) => (
                    <tr key={m.user_id} data-testid={`rolemember-${m.email}`}>
                      <td className="p-3"><div className="font-medium">{m.display_name}{m.is_self ? " (você)" : ""}</div><div className="text-muted">{m.email}</div></td>
                      <td className="p-3">{roleLabel(m.role)}</td>
                      <td className="p-3 text-right">{m.can_change_role ? <MemberRoleChange userId={m.user_id} name={m.display_name} current={m.role} options={assignable} /> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {members.data && !members.data.can_manage_roles && <p className="mt-2 text-xs text-muted">Só o Administrador do provedor e o Gestor de Acesso alteram papéis.</p>}
        </section>

        <section aria-labelledby="h-matrix">
          <h2 id="h-matrix" className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Papéis do sistema</h2>
          {roles.status === 403 ? <p className="panel p-4 text-sm text-muted">Seu papel não permite ver a lista de papéis.</p> : roles.data === null ? <ErrorState title="Falha ao carregar os papéis" /> : (
            <div className="panel overflow-x-auto" data-testid="role-matrix">
              <table className="w-full min-w-[720px] text-sm">
                <caption className="sr-only">Permissões de cada papel do sistema</caption>
                <thead className="text-left text-muted"><tr>
                  <th scope="col" className="p-3 font-medium">Permissão</th>
                  {roles.data.roles.map((r) => <th key={r.role} scope="col" className="p-3 text-center font-medium">{roleLabel(r.role)}</th>)}
                </tr></thead>
                <tbody className="divide-y divide-line">
                  {allPerms.map((p) => (
                    <tr key={p.name}>
                      <th scope="row" className="p-3 text-left font-normal">
                        <div>{p.description}</div>
                        <div className="text-xs text-muted"><code>{p.name}</code> · {RISK[p.risk].label}</div>
                      </th>
                      {roles.data!.roles.map((r) => {
                        const has = r.permissions.some((x) => x.name === p.name);
                        return <td key={r.role} className="p-3 text-center">{has ? <span aria-label="Tem a permissão">✔</span> : <span aria-label="Não tem" className="text-muted">—</span>}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section aria-labelledby="h-history">
          <h2 id="h-history" className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Histórico de mudanças de papel</h2>
          {history.status === 403 ? <p className="panel p-4 text-sm text-muted">Seu papel não permite ver o histórico.</p> : history.data === null ? <ErrorState title="Falha ao carregar o histórico" /> : history.data.items.length === 0 ? <EmptyState title="Nenhuma mudança de papel ainda" /> : (
            <div className="panel overflow-x-auto" data-testid="role-history">
              <table className="w-full min-w-[640px] text-sm">
                <caption className="sr-only">Mudanças de papel, da mais recente para a mais antiga</caption>
                <thead className="text-left text-muted"><tr><th scope="col" className="p-3 font-medium">Quando</th><th scope="col" className="p-3 font-medium">Quem alterou</th><th scope="col" className="p-3 font-medium">De quem</th><th scope="col" className="p-3 font-medium">Mudança</th><th scope="col" className="p-3 font-medium">Motivo</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {history.data.items.map((i) => (
                    <tr key={i.id}>
                      <td className="tabular p-3">{when(i.at)}</td>
                      <td className="p-3">{who(i.actor)}</td>
                      <td className="p-3">{who(i.target)}</td>
                      <td className="p-3">{i.from ? roleLabel(i.from) : "—"} → {i.to ? roleLabel(i.to) : "—"}</td>
                      <td className="p-3">{i.reason ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {history.data.truncated && <p className="p-3 text-xs text-muted">Mostrando as 50 mais recentes.</p>}
            </div>
          )}
        </section>
      </div>
    </AppShell>
  );
}
