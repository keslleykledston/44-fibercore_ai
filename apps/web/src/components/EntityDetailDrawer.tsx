"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** Painel lateral modal (<dialog>): foco preso, Esc fecha, foco volta ao gatilho. Conteúdo vem pronto do servidor/da tabela. */
export function EntityDetailDrawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      data-testid="entity-drawer"
      aria-labelledby="entity-drawer-title"
      onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}
      className="fixed inset-y-0 right-0 left-auto m-0 h-full max-h-none w-full max-w-md border-l border-line bg-surface p-0 text-text shadow-card backdrop:bg-black/40"
    >
      <div className="flex h-full flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-line p-4">
          <h2 id="entity-drawer-title" className="text-lg font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="inline-flex min-h-touch min-w-touch items-center justify-center rounded-btn px-3 text-sm text-accent hover:underline">Fechar</button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </dialog>
  );
}
