"use client";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon";

interface Hit { kind: string; label: string; href: string }
const PAGES: Hit[] = [
  { kind: "Tela", label: "Visão Geral", href: "/" }, { kind: "Tela", label: "Rede", href: "/rede" }, { kind: "Tela", label: "ONUs offline", href: "/rede/offline" }, { kind: "Tela", label: "Dispositivos (CPEs)", href: "/dispositivos" }, { kind: "Tela", label: "Edges", href: "/dispositivos/edges" }, { kind: "Tela", label: "Capacidades", href: "/dispositivos/capacidades" },
  { kind: "Tela", label: "Assinantes", href: "/assinantes" }, { kind: "Tela", label: "NOC", href: "/noc" },
  { kind: "Tela", label: "Operações", href: "/operacoes" }, { kind: "Tela", label: "Equipe e acessos", href: "/administracao/equipe" }, { kind: "Tela", label: "Papéis e permissões", href: "/administracao/papeis" }, { kind: "Tela", label: "Segurança da conta", href: "/conta/seguranca" }, { kind: "Tela", label: "Administração · Módulos", href: "/administracao/modulos" },
  { kind: "Tela", label: "Central de Ajuda", href: "/ajuda" },
];

/** Busca global (⌘/Ctrl+K): telas, atalho para buscar ONU por serial e clientes por nome (a partir de 3 letras, pelo BFF; só id e nome). */
export function CommandPalette() {
  const ref = useRef<HTMLDialogElement>(null);
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const router = useRouter();
  const [people, setPeople] = useState<Hit[]>([]);

  const open = () => { setQ(""); setIdx(0); ref.current?.showModal(); };
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); ref.current?.open ? ref.current.close() : open(); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  useEffect(() => {
    const s = q.trim();
    setPeople([]); // um resultado de outra digitação nunca fica na lista
    if (s.length < 3) return;
    const ctl = new AbortController();
    const t = setTimeout(async () => { // espera o usuário parar de digitar: uma consulta auditada por pausa, não por tecla
      try {
        const r = await fetch(`/bff/search/customers?q=${encodeURIComponent(s)}`, { signal: ctl.signal, cache: "no-store" });
        const d = (await r.json()) as { items?: { id: string; display_name: string }[] };
        if (ctl.signal.aborted) return; // a digitação mudou (ou a paleta fechou) enquanto a resposta chegava: descarta
        setPeople((d.items ?? []).map((c) => ({ kind: "Cliente", label: c.display_name, href: `/assinantes/${c.id}` })));
      } catch { /* cancelada ou indisponível: a busca de telas/ONU continua */ }
    }, 300);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [q]);

  const hits = useMemo<Hit[]>(() => {
    const s = q.trim();
    const pages = PAGES.filter((p) => p.label.toLowerCase().includes(s.toLowerCase()));
    return s ? [{ kind: "ONU", label: `Buscar ONU “${s}”`, href: `/rede?serial=${encodeURIComponent(s)}` }, ...people, ...pages] : pages;
  }, [q, people]);
  const go = (h?: Hit) => { if (!h) return; ref.current?.close(); router.push(h.href); };

  return (
    <>
      <button type="button" onClick={open} aria-haspopup="dialog" aria-label="Abrir busca global"
        className="flex min-h-touch items-center gap-2 rounded-btn border border-line bg-bg px-3 text-sm text-muted hover:bg-surface-2">
        <Icon name="search" /><span className="hidden sm:inline">Buscar</span><kbd className="hidden rounded border border-line px-1.5 text-xs md:inline">⌘K</kbd>
      </button>
      <dialog ref={ref} aria-label="Busca global" onClose={() => { setQ(""); setPeople([]); }} className="m-0 mx-auto mt-[12vh] w-[calc(100%-32px)] max-w-xl rounded-modal border border-line bg-surface p-0 text-text shadow-2xl backdrop:bg-black/30">
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Icon name="search" className="size-4 text-muted" />
          <input autoFocus value={q} aria-label="Buscar telas, ONU por serial ou cliente por nome" placeholder="Digite um serial, um nome de cliente ou de tela" role="combobox" aria-expanded="true" aria-controls="cp-list"
            aria-activedescendant={hits[idx] ? `cp-${idx}` : undefined}
            onChange={(e) => { setQ(e.target.value); setIdx(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, hits.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
              if (e.key === "Enter") { e.preventDefault(); go(hits[idx]); }
            }}
            className="min-h-14 flex-1 bg-transparent text-base outline-none" />
        </div>
        <ul id="cp-list" role="listbox" className="max-h-[50vh] overflow-auto p-2">
          {hits.length === 0 && <li className="px-3 py-6 text-center text-sm text-muted">Nenhum resultado.</li>}
          {hits.map((h, i) => (
            <li key={h.href} id={`cp-${i}`} role="option" aria-selected={i === idx} onMouseEnter={() => setIdx(i)} onClick={() => go(h)}
              className={`flex min-h-11 cursor-pointer items-center gap-3 rounded-btn px-3 py-2 ${i === idx ? "bg-surface-2" : ""}`}>
              <span className="w-12 shrink-0 text-xs text-muted">{h.kind}</span><span className="truncate text-sm font-medium">{h.label}</span>
            </li>
          ))}
        </ul>
      </dialog>
    </>
  );
}
