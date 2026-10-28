"use client";
import Link from "next/link";
import { useRef } from "react";
import { Icon } from "./Icon";

export function MobileMenu({ items, active }: { items: readonly { href: string; label: string; icon: string }[]; active: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  return (
    <>
      <button type="button" aria-label="Abrir menu" aria-haspopup="dialog" onClick={() => ref.current?.showModal()}
        className="flex min-h-touch min-w-touch items-center justify-center rounded-btn hover:bg-surface-2 md:hidden"><Icon name="menu" className="size-5" /></button>
      <dialog ref={ref} aria-label="Menu" className="fixed inset-y-0 left-0 m-0 h-full max-h-none w-72 max-w-[85vw] border-r border-line bg-surface p-3 text-text backdrop:bg-black/30"
        onClick={(e) => { if (e.target === ref.current) ref.current?.close(); }}>
        <div className="mb-2 flex items-center justify-between px-2">
          <span className="text-lg font-semibold tracking-tight">FiberCore</span>
          <button type="button" aria-label="Fechar menu" onClick={() => ref.current?.close()} className="flex min-h-touch min-w-touch items-center justify-center rounded-btn hover:bg-surface-2"><Icon name="close" /></button>
        </div>
        <nav aria-label="Principal (menu)" className="space-y-1">
          {items.map((n) => (
            <Link key={n.href} href={n.href} onClick={() => ref.current?.close()} aria-current={active === n.href ? "page" : undefined}
              className={`flex min-h-touch items-center gap-3 rounded-btn px-3 text-sm ${active === n.href ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-surface-2"}`}>
              <Icon name={n.icon} />{n.label}
            </Link>
          ))}
        </nav>
      </dialog>
    </>
  );
}
