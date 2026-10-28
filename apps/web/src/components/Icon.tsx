// Ícones de traço (grade 24) embutidos: evita dependência extra. Decorativos: o rótulo textual sempre acompanha.
const P: Record<string, string> = {
  home: "M3 11l9-8 9 8M5 10v10h14V10",
  network: "M12 3v6M5 21v-6h14v6M12 9v6M3 21h4M17 21h4M10 21h4",
  users: "M16 11a4 4 0 100-8 4 4 0 000 8zM3 21v-1a6 6 0 0112 0v1M17 14a5 5 0 014 5v2",
  activity: "M3 12h4l3-8 4 16 3-8h4",
  cpu: "M7 7h10v10H7zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6zM19 12a7 7 0 00-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 00-2-1.2L14 3h-4l-.6 2.7a7 7 0 00-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 005 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 002 1.2L10 21h4l.6-2.7a7 7 0 002-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z",
  help: "M12 22a10 10 0 100-20 10 10 0 000 20zM9.5 9a2.5 2.5 0 114 2c-.9.6-1.5 1-1.5 2M12 17h.01",
  search: "M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.3-4.3",
  sun: "M12 17a5 5 0 100-10 5 5 0 000 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z",
  menu: "M3 6h18M3 12h18M3 18h18",
  close: "M6 6l12 12M18 6L6 18",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3zM9 12l2 2 4-4",
  logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
};
export function Icon({ name, className = "size-4" }: { name: keyof typeof P | string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true" focusable="false">
      <path d={P[name] ?? ""} />
    </svg>
  );
}
