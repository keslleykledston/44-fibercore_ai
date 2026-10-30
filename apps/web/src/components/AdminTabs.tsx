import Link from "next/link";

const TABS = [{ href: "/administracao/modulos", label: "Módulos" }, { href: "/administracao/equipe", label: "Equipe e acessos" }];

export function AdminTabs({ current }: { current: string }) {
  return (
    <nav aria-label="Administração" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
      {TABS.map((t) => (
        <Link key={t.href} href={t.href} aria-current={t.href === current ? "page" : undefined}
          className={`inline-flex min-h-touch items-center whitespace-nowrap px-4 text-sm ${t.href === current ? "border-b-2 border-accent font-medium text-text" : "text-muted hover:text-text"}`}>{t.label}</Link>
      ))}
    </nav>
  );
}
