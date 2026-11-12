import Link from "next/link";
import { platformStatus } from "@/lib/platformStatus";

const TABS = [{ href: "/administracao/modulos", label: "Módulos" }, { href: "/administracao/equipe", label: "Equipe e acessos" }];
const PLATFORM_TAB = { href: "/plataforma/organizacoes", label: "Organizações" };   // só para a conta operadora da plataforma: quem não é nunca a vê

export async function AdminTabs({ current }: { current: string }) {
  const tabs = (await platformStatus()).operator ? [...TABS, PLATFORM_TAB] : TABS;
  return (
    <nav aria-label="Administração" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <Link key={t.href} href={t.href} aria-current={t.href === current ? "page" : undefined} data-testid={t === PLATFORM_TAB ? "admin-tab-organizacoes" : undefined}
          className={`inline-flex min-h-touch items-center whitespace-nowrap px-4 text-sm ${t.href === current ? "border-b-2 border-accent font-medium text-text" : "text-muted hover:text-text"}`}>{t.label}</Link>
      ))}
    </nav>
  );
}
