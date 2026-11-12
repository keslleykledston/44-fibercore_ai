import Link from "next/link";
import { cookies, headers } from "next/headers";
import { notFound } from "next/navigation";
import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { FLASH_COOKIE, ORG_ERRORS, ORG_FLASH, ORG_STATUS, type PlatformOrgList, cursorQuery, decodeFlash, inviteLabel, inviteUrl } from "@/lib/platform";
import { platformStatus } from "@/lib/platformStatus";

const field = "min-h-touch rounded-btn border border-line bg-bg px-3";
const when = (iso: string) => new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" });
type Search = { ok?: string | string[]; erro?: string | string[]; nome?: string | string[]; antes?: string | string[] };
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";

/** Organizações da plataforma (ADR-0046 D1). Só a conta operadora: quem não é recebe 404, como se a tela não existisse. Sem JavaScript: formulários comuns → /bff/plataforma/*. */
export default async function Organizacoes({ searchParams }: { searchParams: Promise<Search> }) {
  const status = await platformStatus();
  if (!status.operator) notFound();
  const sp = await searchParams;
  const ok = one(sp.ok), erro = one(sp.erro), nome = one(sp.nome).slice(0, 60);
  const shell = (children: React.ReactNode) => (
    <AppShell active="/administracao/modulos" user="1">
      <PageHeader title="Organizações" subtitle="Provedores desta plataforma. Só a conta operadora da plataforma vê esta tela." helpSlug="administracao/organizacoes" />
      <AdminTabs current="/plataforma/organizacoes" />
      {erro && ORG_ERRORS[erro] && <p role="alert" data-testid="org-erro" className="mb-4 rounded-btn border border-danger px-3 py-2 text-sm text-danger">{ORG_ERRORS[erro]}</p>}
      {ok && ORG_FLASH[ok] && <p role="status" data-testid="org-flash" className="mb-4 rounded-btn border border-ok px-3 py-2 text-sm text-ok">{ORG_FLASH[ok]}</p>}
      {children}
    </AppShell>
  );
  if (!status.mfa_recent) {
    return shell(
      <section aria-label="Confirmar o segundo fator" className="panel max-w-xl p-4" data-testid="org-mfa">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Confirme o segundo fator</h2>
        <p className="mb-3 text-sm text-muted">Criar e listar organizações exige que o segundo fator tenha sido confirmado nos últimos 10 minutos. Digite o código do autenticador (ou um código de recuperação). Quem ainda não ativou o MFA faz isso em <Link href="/conta/seguranca" className="text-accent underline">Conta → Segurança</Link>.</p>
        <form method="post" action="/bff/plataforma/mfa" className="flex flex-wrap items-end gap-3">
          <label className="grid gap-1 text-sm">Código do autenticador
            <input name="code" required minLength={6} maxLength={32} autoComplete="one-time-code" inputMode="numeric" className={field} />
          </label>
          <button type="submit" data-testid="org-mfa-enviar" className="min-h-touch rounded-btn bg-accent px-4 text-sm font-medium text-[color:var(--on-accent)]">Confirmar</button>
        </form>
      </section>,
    );
  }
  const antes = cursorQuery(one(sp.antes));   // cursor da página (só um instante e um id no formato certo; qualquer outra coisa volta à primeira página)
  const [list, jar, hdr] = await Promise.all([apiSafe<PlatformOrgList>(`/v1/platform/organizations${antes ? `?${antes}` : ""}`), cookies(), headers()]);
  if (list.status === 403 && list.detail !== "mfa_recent_required") notFound();
  const flash = ok === "criada" ? decodeFlash(jar.get(FLASH_COOKIE)?.value) : null;
  const host = hdr.get("x-forwarded-host") ?? hdr.get("host") ?? "";
  const base = host ? `${hdr.get("x-forwarded-proto") ?? (host.startsWith("127.0.0.1") || host.startsWith("localhost") ? "http" : "https")}://${host}` : "";
  const items = list.data?.items ?? [];
  return shell(
    <div className="grid gap-6">
      {ok === "criada" && (
        <section aria-label="Organização criada" className="panel border-ok p-4" data-testid="org-criada" role="status">
          <h2 className="font-semibold text-ok">Organização criada{flash ? `: ${flash.name}` : ""}</h2>
          {flash ? (
            <div className="mt-2 grid gap-2 text-sm">
              <p>Convite do primeiro administrador (<strong>{flash.email}</strong>): <strong data-testid="org-convite-estado">pendente</strong>, válido até <time dateTime={flash.expires}>{when(flash.expires)}</time> (72 horas). Nada foi enviado por e-mail: copie o link e envie à pessoa.</p>
              <label className="grid gap-1">Link do convite (aparece só agora)
                <input readOnly value={inviteUrl(base, flash.token)} data-testid="org-convite-link" className={`${field} font-mono text-xs`} />
              </label>
              <p className="text-muted">Você não passa a ser membro da organização. Se o link expirar sem ser usado, peça ao dono do sistema (linha de comando) para incluir o administrador.</p>
              <form method="post" action="/bff/plataforma/ocultar"><button type="submit" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg">Ocultar o link</button></form>
            </div>
          ) : (
            <p className="mt-2 text-sm text-muted">A organização foi criada. O link do convite já não está mais disponível nesta tela (vale por 2 minutos e aparece uma vez); veja o estado do convite na lista abaixo.</p>
          )}
        </section>
      )}
      <section aria-label="Organizações" data-testid="org-lista">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Organizações ({list.data ? list.data.total : items.length})</h2>
        {list.data === null ? <ErrorState title="Falha ao carregar as organizações" hint="Tente de novo em instantes." /> : items.length === 0 ? <EmptyState title="Nenhuma organização" /> : (
          <div className="panel overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <caption className="sr-only">Organizações da plataforma: nome, estado, quantidade de Edges, OLTs e ONUs, quem e quando criou e o estado do convite do primeiro administrador</caption>
              <thead className="text-left text-muted"><tr>
                <th scope="col" className="p-3 font-medium">Organização</th><th scope="col" className="p-3 font-medium">Estado</th><th scope="col" className="p-3 text-right font-medium">Edges</th>
                <th scope="col" className="p-3 text-right font-medium">OLTs</th><th scope="col" className="p-3 text-right font-medium">ONUs</th><th scope="col" className="p-3 font-medium">Criada</th><th scope="col" className="p-3 font-medium">Convite</th>
              </tr></thead>
              <tbody className="divide-y divide-line">
                {items.map((o) => (
                  <tr key={o.id} data-testid="org-linha">
                    <th scope="row" className="p-3 text-left font-medium">{o.name}</th>
                    <td className="p-3"><span aria-hidden>{o.status === "active" ? "●" : "▲"} </span>{ORG_STATUS[o.status] ?? o.status}</td>
                    <td className="tabular p-3 text-right">{o.edges}</td><td className="tabular p-3 text-right">{o.olts}</td><td className="tabular p-3 text-right">{o.onus}</td>
                    <td className="p-3"><time dateTime={o.created_at}>{when(o.created_at)}</time>
                      <span className="block text-xs text-muted">{o.created_via === "screen" ? `pela tela, por ${o.created_by ?? "conta alegada"} (alegado)` : "pela linha de comando do dono"}</span>
                      {o.api_trail === false && <span className="block text-xs text-warn" data-testid="org-sem-par">Sem o par de auditoria da API: revisar.</span>}
                    </td>
                    <td className="p-3">{inviteLabel(o.invite_state)}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>
        )}
        {list.data?.next && (
          <p className="mt-2"><Link href={`/plataforma/organizacoes?antes=${encodeURIComponent(`${list.data.next.before_at}~${list.data.next.before_id}`)}`} data-testid="org-mais-antigas"
            className="inline-flex min-h-touch items-center rounded-btn border border-line px-3 text-sm hover:bg-bg">Ver organizações mais antigas</Link></p>
        )}
        {antes && <p className="mt-2"><Link href="/plataforma/organizacoes" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar às mais recentes</Link></p>}
        <p className="mt-2 text-xs text-muted">Só contagens e rótulos: nenhum dado de assinante, de OLT ou de ONU aparece aqui. Suspender ou reativar uma organização é feito pelo dono do sistema.</p>
      </section>
      <section aria-label="Nova organização" className="panel p-4" data-testid="org-nova">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Nova organização</h2>
        <p className="mb-3 text-sm text-muted">Cria a organização vazia (sem OLT, Edge nem recurso ligado) e um convite de 72 horas para o primeiro administrador. No máximo 5 criações por hora. O link do convite aparece uma única vez, depois da criação.</p>
        <form method="post" action="/bff/plataforma/organizacoes" className="grid gap-3 md:grid-cols-3">
          <label className="grid gap-1 text-sm">Nome da organização
            <input name="name" required minLength={2} maxLength={60} defaultValue={nome} autoComplete="off" aria-describedby="org-nome-ajuda" className={field} />
            <span id="org-nome-ajuda" className="text-xs text-muted">De 2 a 60 caracteres; não pode repetir um nome existente.</span>
          </label>
          <label className="grid gap-1 text-sm">E-mail do primeiro administrador
            <input name="admin_email" type="email" required maxLength={254} autoComplete="off" className={field} />
          </label>
          <label className="grid gap-1 text-sm">Nome do primeiro administrador (opcional)
            <input name="admin_name" maxLength={100} autoComplete="off" className={field} />
          </label>
          <div className="md:col-span-3"><button type="submit" data-testid="org-criar" className="min-h-touch rounded-btn bg-accent px-4 text-sm font-medium text-[color:var(--on-accent)]">Criar organização</button></div>
        </form>
      </section>
    </div>,
  );
}

export const dynamic = "force-dynamic";
