import Link from "next/link";
import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { Avatar } from "@/components/Avatar";
import { InviteActions } from "@/components/InviteActions";
import { InviteDrawer } from "@/components/InviteDrawer";
import { PersonManage } from "@/components/PersonManage";
import { PlatformDelegations, RevokeDelegation } from "@/components/PlatformDelegations";
import { TeamTabs } from "@/components/TeamTabs";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { RISK } from "@/lib/roles";
import { ACTIVITY_FILTERS, ago, sentence, when } from "@/lib/team";
import type { MeInfo, PermissionInfo, PlatformDelegationList, RoleList, Team, TeamActivity } from "@/lib/types";

type Search = { aba?: string; q?: string; funcao?: string; tipo?: string };
const ABAS = new Set(["pessoas", "funcoes", "atividade"]);
const CELL = { all: { text: "Sim", icon: "✔", cls: "text-ok" }, some: { text: "Em parte", icon: "◐", cls: "text-warn" }, none: { text: "Não", icon: "—", cls: "text-muted" } } as const;

function Summary({ t }: { t: Team }) {
  const items = [
    { k: "Pessoas ativas", v: t.summary.active, hint: "com acesso hoje" },
    { k: "Convites pendentes", v: t.summary.pending_invites, hint: "aguardando a pessoa aceitar" },
    { k: "Sem verificação em 2 etapas", v: t.summary.without_mfa, hint: "senha é a única proteção" },
  ];
  return (
    <dl className="mb-4 grid gap-3 sm:grid-cols-3" data-testid="team-summary">
      {items.map((i) => (
        <div key={i.k} className="panel p-4"><dt className="text-sm text-muted">{i.k}</dt><dd className="mt-1 text-2xl font-semibold tabular-nums">{i.v}</dd><dd className="text-xs text-muted">{i.hint}</dd></div>
      ))}
    </dl>
  );
}

type Row = {
  key: string; name: string; email: string; role: string; role_label: string; summary: string; kind: "member" | "invite"; self: boolean;
  mfa: boolean | null; status: "ativo" | "pendente" | "vencido"; note: string | null; testid: string;
};

function rowsOf(t: Team, q: string, funcao: string): Row[] {
  const needle = q.trim().toLowerCase();
  const info = new Map(t.roles.map((r) => [r.role, r.summary]));
  const members: Row[] = t.members.map((m) => ({ key: m.user_id, name: m.name, email: m.email, role: m.role, role_label: m.role_label, summary: m.role_summary, kind: "member", self: m.is_self,
    mfa: m.mfa_enabled, status: "ativo", note: null, testid: `person-${m.email}` }));
  const invites: Row[] = t.invites.map((i) => ({ key: i.id, name: i.name ?? "", email: i.email, role: i.role, role_label: i.role_label, summary: info.get(i.role) ?? "", kind: "invite", self: false,
    mfa: null, status: i.expired ? "vencido" : "pendente", testid: `invite-${i.email}`,
    note: `${i.by ? `Convidado por ${i.by} ` : "Convidado "}${ago(i.created_at)} · ${i.expired ? "link vencido, gere outro" : `vale até ${when(i.expires_at)}`}` }));
  return [...members, ...invites].filter((r) => (!needle || `${r.name} ${r.email}`.toLowerCase().includes(needle)) && (!funcao || r.role === funcao));
}

const PILL = "inline-flex items-center rounded-btn border px-2 py-0.5 text-xs";
function Status({ r }: { r: Row }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {r.status === "ativo" && <span className={`${PILL} border-ok text-ok`}>Ativo</span>}
      {r.status === "pendente" && <span className={`${PILL} border-accent text-accent`}>Convite pendente</span>}
      {r.status === "vencido" && <span className={`${PILL} border-warn text-warn`}>Convite vencido</span>}
      {r.mfa === true && <span className={`${PILL} border-ok text-ok`}>2 etapas ligada</span>}
      {r.mfa === false && <span className={`${PILL} border-line text-muted`}>2 etapas desligada</span>}
    </div>
  );
}
function Who({ r }: { r: Row }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <Avatar name={r.name || r.email} />
      <div className="min-w-0">
        <div className="font-medium">{r.name || <span className="text-muted">Sem nome ainda</span>}{r.self ? " (você)" : ""}</div>
        <div className="truncate text-sm text-muted">{r.email}</div>
        {r.note && <div className="text-xs text-muted">{r.note}</div>}
      </div>
    </div>
  );
}
function Role({ r }: { r: Row }) {
  return <div><div className="text-sm font-medium" data-testid="person-role">{r.role_label}</div><div className="max-w-72 text-xs text-muted">{r.summary}</div></div>;
}

function People({ t, q, funcao }: { t: Team; q: string; funcao: string }) {
  const rows = rowsOf(t, q, funcao);
  const memberOf = new Map(t.members.map((m) => [m.user_id, m]));
  const action = (r: Row) => {
    if (r.self) return <Link href="/conta/seguranca" data-testid="my-security" className="inline-flex min-h-touch items-center rounded-btn border border-line px-3 text-sm hover:bg-bg">Minha segurança</Link>;
    if (!t.me.can_manage) return null;
    if (r.kind === "invite") return <InviteActions id={r.key} email={r.email} />;
    const m = memberOf.get(r.key)!;
    return <PersonManage m={m} roles={t.roles} canManage={t.me.can_manage} />;
  };
  return (
    <div className="grid gap-4">
      <form method="get" className="flex flex-wrap items-end gap-2" role="search" aria-label="Filtrar pessoas">
        <input type="hidden" name="aba" value="pessoas" />
        <label className="grid gap-1 text-sm">Buscar<input name="q" defaultValue={q} placeholder="Nome ou e-mail" className="min-h-touch rounded-btn border border-line bg-bg px-3" /></label>
        <label className="grid gap-1 text-sm">Função
          <select name="funcao" defaultValue={funcao} className="min-h-touch rounded-btn border border-line bg-bg px-3">
            <option value="">Todas</option>
            {t.roles.map((r) => <option key={r.role} value={r.role}>{r.label}</option>)}
          </select>
        </label>
        <button type="submit" className="min-h-touch rounded-btn border border-line px-4 hover:bg-bg">Filtrar</button>
        {(q || funcao) && <Link href="/administracao/equipe?aba=pessoas" className="inline-flex min-h-touch items-center px-2 text-sm text-accent hover:underline">Limpar</Link>}
      </form>
      {rows.length === 0 ? (
        <EmptyState title={q || funcao ? "Ninguém encontrado" : "Só você está na equipe por enquanto"} hint={q || funcao ? "Mude a busca ou o filtro de função." : "Convide quem trabalha com você: leva menos de um minuto."} />
      ) : (
        <>
          <p className="text-sm text-muted" aria-live="polite">{rows.length} {rows.length === 1 ? "registro" : "registros"}</p>
          <div className="panel hidden overflow-hidden md:block" data-testid="people-list">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Pessoas da equipe e convites pendentes</caption>
              <thead className="bg-surface-2 text-xs text-muted"><tr><th scope="col" className="px-4 py-3 font-medium">Pessoa</th><th scope="col" className="px-4 py-3 font-medium">Função</th><th scope="col" className="px-4 py-3 font-medium">Situação</th><th scope="col" className="px-4 py-3 text-right font-medium"><span className="sr-only">Ações</span></th></tr></thead>
              <tbody className="divide-y divide-line">
                {rows.map((r) => (
                  <tr key={r.key} data-testid={r.testid} className="align-middle">
                    <td className="max-w-80 px-4 py-3"><Who r={r} /></td>
                    <td className="px-4 py-3"><Role r={r} /></td>
                    <td className="px-4 py-3"><Status r={r} /></td>
                    <td className="px-4 py-3 text-right">{action(r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ul className="grid gap-3 md:hidden" aria-label="Pessoas da equipe e convites pendentes">
            {rows.map((r) => (
              <li key={r.key} className="panel grid gap-3 p-4" data-testid={`m-${r.testid}`}>
                <Who r={r} /><Role r={r} /><Status r={r} />
                <div className="flex justify-end border-t border-line pt-2">{action(r)}</div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Roles({ t, technical }: { t: Team; technical: RoleList | null }) {
  const groups = t.capabilities.groups;
  const roles = t.roles;
  const perms: PermissionInfo[] = [];
  for (const r of technical?.roles ?? []) for (const p of r.permissions) if (!perms.some((x) => x.name === p.name)) perms.push(p);
  perms.sort((a, b) => b.risk.localeCompare(a.risk) || a.name.localeCompare(b.name));
  return (
    <div className="grid gap-6">
      <section aria-labelledby="h-cards" className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" data-testid="role-cards">
        <h2 id="h-cards" className="sr-only">Funções</h2>
        {roles.map((r) => (
          <article key={r.role} className="panel p-4 text-sm">
            <h3 className="text-base font-semibold">{r.label}</h3>
            <p className="mt-1 text-muted">{r.summary}</p>
            {r.can.length > 0 && <ul className="mt-2 list-disc pl-5">{r.can.map((c) => <li key={c}>{c}</li>)}</ul>}
            {r.cannot.length > 0 && <p className="mt-2 text-muted"><strong>Não pode:</strong> {r.cannot.join("; ")}.</p>}
          </article>
        ))}
      </section>

      <section aria-labelledby="h-matrix">
        <h2 id="h-matrix" className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Quem pode o quê</h2>
        <div className="panel overflow-x-auto" data-testid="role-matrix">
          <table className="w-full min-w-[720px] text-sm">
            <caption className="sr-only">Capacidades de cada função</caption>
            <thead className="text-left text-muted"><tr><th scope="col" className="p-3 font-medium">Capacidade</th>{roles.map((r) => <th key={r.role} scope="col" className="p-3 text-center font-medium">{r.label}</th>)}</tr></thead>
            <tbody className="divide-y divide-line">
              {groups.map((g) => (
                <tr key={g.id}>
                  <th scope="row" className="p-3 text-left font-normal">{g.label}</th>
                  {roles.map((r) => { const c = CELL[t.capabilities.matrix[r.role]?.[g.id] ?? "none"]; return <td key={r.role} className={`p-3 text-center ${c.cls}`}><span aria-hidden>{c.icon} </span>{c.text}</td>; })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {perms.length > 0 && (
        <details className="panel p-4 text-sm" data-testid="technical-details">
          <summary className="cursor-pointer font-medium">Ver detalhes técnicos (permissões)</summary>
          <p className="mt-2 text-muted">Para quem precisa auditar: a lista exata de permissões de cada função.</p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <caption className="sr-only">Permissões técnicas de cada função</caption>
              <thead className="text-left text-muted"><tr><th scope="col" className="p-2 font-medium">Permissão</th>{technical!.roles.map((r) => <th key={r.role} scope="col" className="p-2 text-center font-medium">{r.label}</th>)}</tr></thead>
              <tbody className="divide-y divide-line">
                {perms.map((p) => (
                  <tr key={p.name}>
                    <th scope="row" className="p-2 text-left font-normal"><div>{p.description}</div><div className="text-xs text-muted"><code>{p.name}</code> · {RISK[p.risk].label}</div></th>
                    {technical!.roles.map((r) => <td key={r.role} className="p-2 text-center">{r.permissions.some((x) => x.name === p.name) ? <span aria-label="Tem">✔</span> : <span aria-label="Não tem" className="text-muted">—</span>}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}

function Activity({ a, tipo }: { a: TeamActivity | null; tipo: string }) {
  const f = ACTIVITY_FILTERS.find((x) => x.id === tipo) ?? ACTIVITY_FILTERS[0];
  const items = (a?.items ?? []).filter((i) => f.kinds.length === 0 || f.kinds.includes(i.kind));
  return (
    <div className="grid gap-4">
      <nav aria-label="Tipo de atividade" className="flex flex-wrap gap-2">
        {ACTIVITY_FILTERS.map((x) => (
          <Link key={x.id} href={`/administracao/equipe?aba=atividade${x.id ? `&tipo=${x.id}` : ""}`} aria-current={x.id === f.id ? "true" : undefined}
            className={`inline-flex min-h-touch items-center rounded-btn border px-3 text-sm ${x.id === f.id ? "border-accent bg-accent-soft font-medium" : "border-line hover:bg-bg"}`}>{x.label}</Link>
        ))}
      </nav>
      {a === null ? <p className="panel p-4 text-sm text-muted">Seu papel não permite ver a atividade.</p> : items.length === 0 ? <EmptyState title="Nada por aqui ainda" hint="Convites, mudanças de função e remoções aparecem nesta lista." /> : (
        <ol className="panel divide-y divide-line" data-testid="activity-list">
          {items.map((i) => <li key={i.id} className="p-3 text-sm"><div>{sentence(i)}</div><div className="text-xs text-muted">{when(i.at)}</div></li>)}
        </ol>
      )}
      {a?.truncated && <p className="text-xs text-muted">Mostrando as mais recentes.</p>}
    </div>
  );
}

export default async function Equipe({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const aba = ABAS.has(sp.aba ?? "") ? (sp.aba as string) : "pessoas";
  const [team, me, activity, technical, deleg] = await Promise.all([
    apiSafe<Team>("/v1/team"), apiSafe<MeInfo>("/v1/auth/me"),
    aba === "atividade" ? apiSafe<TeamActivity>("/v1/team/activity?limit=100") : Promise.resolve({ data: null, status: 0 }),
    aba === "funcoes" ? apiSafe<RoleList>("/v1/roles") : Promise.resolve({ data: null, status: 0 }),
    aba === "pessoas" ? apiSafe<PlatformDelegationList>("/v1/platform-delegations?limit=30") : Promise.resolve({ data: null, status: 0 }),
  ]);
  const shell = (children: React.ReactNode) => (
    <AppShell active="/administracao/modulos" user="1">
      <PageHeader title="Equipe e acessos" subtitle="Quem entra, o que cada pessoa pode fazer e o que mudou" helpSlug="administracao/equipe-e-acessos">
        {team.data?.me.can_manage ? <InviteDrawer roles={team.data.roles} /> : null}
      </PageHeader>
      <AdminTabs current="/administracao/equipe" />
      {children}
    </AppShell>
  );
  if (team.status === 403) return shell(<ErrorState title="Sem permissão" hint="Seu papel não permite ver a equipe. Peça a um Administrador." />);
  if (team.data === null) return shell(<ErrorState title="Falha ao carregar a equipe" hint="Tente de novo em instantes." />);
  const t = team.data;
  return shell(
    <div data-testid="team-ready">
      {t.members.some((m) => m.is_self && !m.mfa_enabled) && (
        <div role="status" data-testid="my-mfa-banner" className="panel mb-4 flex flex-wrap items-center justify-between gap-3 border-warn p-4 text-sm">
          <span><strong>Ative a sua verificação em duas etapas.</strong> Ela protege a sua conta: {me.data?.mfa_recent?.enforced ? "o código é pedido ao entrar e, em algumas ações sensíveis, de novo na hora." : "o código é pedido só ao entrar na plataforma."}</span>
          <Link href="/conta/seguranca" className="inline-flex min-h-touch items-center rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">Ativar agora</Link>
        </div>
      )}
      <Summary t={t} />
      <TeamTabs current={aba} />
      {aba === "pessoas" && (
        <div className="grid gap-6">
          <People t={t} q={sp.q ?? ""} funcao={sp.funcao ?? ""} />
          {deleg.data && (
            <details className="panel p-4" data-testid="platform-access">
              <summary className="cursor-pointer text-sm font-medium">Suporte da plataforma (acesso temporário)</summary>
              <div className="mt-3 grid gap-3 text-sm">
                <PlatformDelegations canDelegate={deleg.data.can_delegate} maxHours={deleg.data.max_hours} />
                {deleg.data.items.length === 0 ? <p className="text-muted">Nenhum acesso temporário concedido.</p> : (
                  <ul className="divide-y divide-line" data-testid="delegations">
                    {deleg.data.items.map((d) => (
                      <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 py-2">
                        <div>
                          <div className="font-medium">{d.delegate_name} <span className="font-normal text-muted">· {d.delegate_email}</span></div>
                          <div className="text-xs text-muted">{d.reason} · {d.status === "active" ? `ativo até ${when(d.expires_at)}` : d.status === "revoked" ? `encerrado${d.revoked_at ? ` em ${when(d.revoked_at)}` : ""}` : "vencido"}</div>
                        </div>
                        {d.status === "active" && deleg.data!.can_delegate ? <RevokeDelegation id={d.id} who={d.delegate_email} /> : null}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </details>
          )}
        </div>
      )}
      {aba === "funcoes" && <Roles t={t} technical={technical.data} />}
      {aba === "atividade" && <Activity a={activity.data} tipo={sp.tipo ?? ""} />}
    </div>,
  );
}
