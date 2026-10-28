import { notFound, redirect } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { Markdown } from "@/components/Markdown";
import { getArticle, safeSlug } from "@/lib/help";
import { getSession } from "@/lib/session";

export default async function Artigo({ params }: { params: Promise<{ slug: string[] }> }) {
  if (!(await getSession()).token) redirect("/login");
  const slug = safeSlug((await params).slug);
  const art = slug ? getArticle(slug) : null;
  if (!art) notFound();
  return (
    <AppShell active="/ajuda" user="1">
      <article className="panel mx-auto max-w-3xl p-6 md:p-10" data-testid="help-article">
        {art.status !== "published" && (
          <p role="status" className="mb-4 rounded-btn border border-line bg-bg p-3 text-sm text-muted">Artigo em elaboração: ainda sem capturas de tela validadas.</p>
        )}
        <Markdown source={art.body} />
        <footer className="mt-8 border-t border-line pt-3 text-xs text-muted">
          Versão do produto: {art.meta.product_version ?? "—"} · Última validação: {art.meta.last_verified ?? "—"}
        </footer>
      </article>
    </AppShell>
  );
}
