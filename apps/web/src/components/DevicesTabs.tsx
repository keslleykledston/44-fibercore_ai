import Link from "next/link";

const TABS = [
  { href: "/rede", label: "Inventário" }, { href: "/rede/offline", label: "ONUs offline" }, { href: "/dispositivos", label: "CPEs" },
  { href: "/dispositivos/edges", label: "Edges" }, { href: "/dispositivos/capacidades", label: "Capacidades" },
];

/** Abas da área Rede/Dispositivos (a área continua sendo uma só no menu: o design system limita a 6). */
export function DevicesTabs({ current }: { current: string }) {
  return (
    <nav aria-label="Rede e dispositivos" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
      {TABS.map((t) => (
        <Link key={t.href} href={t.href} aria-current={t.href === current ? "page" : undefined}
          className={`inline-flex min-h-touch items-center whitespace-nowrap px-4 text-sm ${t.href === current ? "border-b-2 border-accent font-medium text-text" : "text-muted hover:text-text"}`}>{t.label}</Link>
      ))}
    </nav>
  );
}
