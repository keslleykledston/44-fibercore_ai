import Link from "next/link";
import type { ReactNode } from "react";

// Máx. 6 áreas (design system). Itens sem tela implementada ficam fora do menu até existirem.
export const NAV = [
  { href: "/", label: "Visão Geral" },
  { href: "/rede", label: "Rede" },
  { href: "/assinantes", label: "Assinantes" },
  { href: "/noc", label: "NOC" },
  { href: "/operacoes", label: "Operações" },
  { href: "/administracao/modulos", label: "Administração" },
] as const; // 6 áreas (limite do design system); a Ajuda fica na barra superior

export function AppShell({ active, children, user }: { active: string; children: ReactNode; user?: string }) {
  return (
    <div className="min-h-screen md:grid md:grid-cols-[232px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-10 focus:bg-surface focus:p-3">Ir para o conteúdo</a>
      <aside className="border-b border-line bg-surface md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-4 py-4 md:block">
          <span className="text-lg font-semibold tracking-tight">FiberCore</span>
        </div>
        <nav aria-label="Principal" className="flex gap-1 overflow-x-auto px-2 pb-2 md:block md:space-y-1 md:px-3">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={active === n.href ? "page" : undefined}
              className={`flex min-h-touch items-center whitespace-nowrap rounded-btn px-3 text-sm ${active === n.href ? "bg-bg font-medium" : "text-muted hover:bg-bg"}`}>
              {n.label}
            </Link>
          ))}
        </nav>
      </aside>
      <div className="min-w-0">
        <header className="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3 md:px-8">
          <form action="/rede" method="get" role="search" className="w-full max-w-md">
            <label htmlFor="q" className="sr-only">Buscar ONU por serial</label>
            <input id="q" name="serial" placeholder="Buscar ONU por serial" autoComplete="off"
              className="min-h-touch w-full rounded-btn border border-line bg-bg px-3 text-sm" />
          </form>
          <div className="flex items-center">
            <Link href="/ajuda" aria-current={active === "/ajuda" ? "page" : undefined} className="flex min-h-touch items-center rounded-btn px-3 text-sm text-muted hover:bg-bg">Ajuda</Link>
            {user && (
              <form action="/bff/logout" method="post">
                <button className="min-h-touch rounded-btn px-3 text-sm text-muted hover:bg-bg" type="submit">Sair</button>
              </form>
            )}
          </div>
        </header>
        <main id="main" className="mx-auto max-w-page px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}
