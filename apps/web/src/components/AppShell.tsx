import Link from "next/link";
import type { ReactNode } from "react";

import { CommandPalette } from "./CommandPalette";
import { Icon } from "./Icon";
import { MobileMenu } from "./MobileMenu";
import { ThemeToggle } from "./ThemeToggle";

// Máx. 6 áreas (design system). Itens sem tela implementada ficam fora do menu até existirem.
export const NAV = [
  { href: "/", label: "Visão Geral", icon: "home" },
  { href: "/rede", label: "Rede", icon: "network" },
  { href: "/assinantes", label: "Assinantes", icon: "users" },
  { href: "/noc", label: "NOC", icon: "activity" },
  { href: "/operacoes", label: "Operações", icon: "cpu" },
  { href: "/administracao/modulos", label: "Administração", icon: "settings" },
] as const; // 6 áreas (limite do design system); a Ajuda fica na barra superior

export function AppShell({ active, children, user }: { active: string; children: ReactNode; user?: string }) {
  return (
    <div className="min-h-screen md:grid md:grid-cols-[232px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-10 focus:bg-surface focus:p-3">Ir para o conteúdo</a>
      <aside className="hidden border-r border-line bg-surface md:block">
        <div className="sticky top-0 p-3">
          <div className="px-3 py-3 text-lg font-semibold tracking-tight">FiberCore</div>
          <nav aria-label="Principal" className="space-y-1">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} aria-current={active === n.href ? "page" : undefined}
                className={`flex min-h-touch items-center gap-3 whitespace-nowrap rounded-btn px-3 text-sm ${active === n.href ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-surface-2"}`}>
                <Icon name={n.icon} />{n.label}
              </Link>
            ))}
          </nav>
        </div>
      </aside>
      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-2 border-b border-line bg-surface px-4 py-2 md:px-8">
          <div className="flex items-center gap-2 md:hidden"><MobileMenu items={NAV} active={active} /><span className="font-semibold tracking-tight">FiberCore</span></div>
          <form action="/rede" method="get" role="search" className="hidden w-full max-w-md md:block">
            <label htmlFor="q" className="sr-only">Buscar ONU por serial</label>
            <input id="q" name="serial" placeholder="Buscar ONU por serial" autoComplete="off"
              className="min-h-touch w-full rounded-btn border border-line bg-bg px-3 text-sm" />
          </form>
          <div className="flex items-center gap-1">
            <CommandPalette />
            <Link href="/ajuda" aria-label="Ajuda" aria-current={active === "/ajuda" ? "page" : undefined} className="flex min-h-touch items-center gap-2 rounded-btn px-3 text-sm text-muted hover:bg-surface-2"><Icon name="help" /><span className="hidden sm:inline">Ajuda</span></Link>
            <ThemeToggle />
            {user && (
              <Link href="/conta/seguranca" aria-label="Segurança da conta" aria-current={active === "/conta/seguranca" ? "page" : undefined} className="flex min-h-touch items-center gap-2 rounded-btn px-3 text-sm text-muted hover:bg-surface-2"><Icon name="shield" /><span className="hidden sm:inline">Conta</span></Link>
            )}
            {user && (
              <form action="/bff/logout" method="post">
                <button className="flex min-h-touch items-center gap-2 rounded-btn px-3 text-sm text-muted hover:bg-surface-2" type="submit" aria-label="Sair"><Icon name="logout" /><span className="hidden sm:inline">Sair</span></button>
              </form>
            )}
          </div>
        </header>
        <main id="main" className="mx-auto max-w-page px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}
