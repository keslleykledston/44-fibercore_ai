import Link from "next/link";

const TABS = [{ id: "pessoas", label: "Pessoas" }, { id: "funcoes", label: "Funções" }, { id: "atividade", label: "Atividade" }];

/** Abas da tela de equipe: links comuns (a aba vem na URL), acessíveis por teclado e sem JavaScript. */
export function TeamTabs({ current }: { current: string }) {
  return (
    <nav aria-label="Seções da equipe" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
      {TABS.map((t) => (
        <Link key={t.id} href={`/administracao/equipe?aba=${t.id}`} aria-current={t.id === current ? "page" : undefined} data-testid={`team-tab-${t.id}`}
          className={`inline-flex min-h-touch items-center whitespace-nowrap px-4 text-sm ${t.id === current ? "border-b-2 border-accent font-medium text-text" : "text-muted hover:text-text"}`}>{t.label}</Link>
      ))}
    </nav>
  );
}
