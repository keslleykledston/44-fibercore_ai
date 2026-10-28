"use client";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon";

interface Hit { kind: string; label: string; href: string }
const PAGES: Hit[] = [
  { kind: "Tela", label: "Visão Geral", href: "/" }, { kind: "Tela", label: "Rede", href: "/rede" },
  { kind: "Tela", label: "Assinantes", href: "/assinantes" }, { kind: "Tela", label: "NOC", href: "/noc" },
  { kind: "Tela", label: "Operações", href: "/operacoes" }, { kind: "Tela", label: "Administração · Módulos", href: "/administracao/modulos" },
  { kind: "Tela", label: "Central de Ajuda", href: "/ajuda" },
];

/** Busca global (⌘/Ctrl+K): telas e atalho para buscar ONU por serial. Sem chamada de API própria. */
export function CommandPalette() {
  const ref = useRef<HTMLDialogElement>(null);
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const router = useRouter();

  const open = () => { setQ(""); setIdx(0); ref.current?.showModal(); };
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); ref.current?.open ? ref.current.close() : open(); } };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const hits = useMemo<Hit[]>(() => {
    const s = q.trim();
    const pages = PAGES.filter((p) => p.label.toLowerCase().includes(s.toLowerCase()));
    return s ? [{ kind: "ONU", label: `Buscar ONU “${s}”`, href: `/rede?serial=${encodeURIComponent(s)}` }, ...pages] : pages;
  }, [q]);
  const go = (h?: Hit) => { if (!h) return; ref.current?.close(); router.push(h.href); };

  return (
    <>
      <button type="button" onClick={open} aria-haspopup="dialog" aria-label="Abrir busca global"
        className="flex min-h-touch items-center gap-2 rounded-btn border border-line bg-bg px-3 text-sm text-muted hover:bg-surface-2">
        <Icon name="search" /><span className="hidden sm:inline">Buscar</span><kbd className="hidden rounded border border-line px-1.5 text-xs md:inline">⌘K</kbd>
      </button>
      <dialog ref={ref} aria-label="Busca global" className="m-0 mx-auto mt-[12vh] w-[calc(100%-32px)] max-w-xl rounded-modal border border-line bg-surface p-0 text-text shadow-2xl backdrop:bg-black/30">
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Icon name="search" className="size-4 text-muted" />
          <input autoFocus value={q} aria-label="Buscar telas ou ONU por serial" placeholder="Digite um serial ou o nome de uma tela" role="combobox" aria-expanded="true" aria-controls="cp-list"
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
