import Link from "next/link";
import { redirect } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { EmptyState, PageHeader } from "@/components/ui";
import { searchArticles } from "@/lib/help";
import { getSession } from "@/lib/session";

export default async function Ajuda({ searchParams }: { searchParams: Promise<{ q?: string }> }) {
  if (!(await getSession()).token) redirect("/login");
  const { q = "" } = await searchParams;
  const arts = searchArticles(q.slice(0, 80));
  return (
    <AppShell active="/ajuda" user="1">
      <PageHeader title="Central de Ajuda" subtitle="Passo a passo para as tarefas do dia a dia" helpSlug="ajuda/central-de-ajuda" />
      <form action="/ajuda" method="get" role="search" className="mb-6 max-w-lg">
        <label htmlFor="hq" className="sr-only">Buscar na ajuda</label>
        <input id="hq" name="q" defaultValue={q} maxLength={80} placeholder="Buscar na ajuda" className="min-h-touch w-full rounded-btn border border-line bg-surface px-3 text-sm" />
      </form>
      {arts.length === 0 ? <EmptyState title="Nenhum artigo encontrado" /> : (
        <ul className="panel divide-y divide-line" data-testid="help-list">
          {arts.map((a) => (
            <li key={a.slug}><Link href={`/ajuda/${a.slug}`} className="flex min-h-touch items-center justify-between gap-3 p-4 hover:bg-bg">
              <span className="font-medium">{a.title}</span>
              {a.status !== "published" && <span className="text-xs text-muted">em elaboração</span>}
            </Link></li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}
