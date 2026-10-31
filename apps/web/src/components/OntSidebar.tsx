"use client";

import { useEffect, useRef, useState } from "react";
import { DeviceThumbnail, type Tone } from "@/components/DeviceThumbnail";
import { OntFormBody, ago, useOntForm } from "@/components/OntConfigView";
import { STATE_TEXT } from "@/lib/ont-config";

/** Sidebar direito recolhível com a configuração do aparelho (SOMENTE LEITURA), na ONU 360°. Não é modal: a página por trás continua navegável. Só mostra o que a API disse que foi observado.
 *  Os formulários são os mesmos do painel de gestão da lista (`OntFormBody`). */
export function OntSidebar({ cpeId, identity }: { cpeId: string; identity: string }) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const { load, form, retry } = useOntForm(cpeId, open);
  useEffect(() => { if (open) panel.current?.focus(); }, [open]);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  const newest = form?.groups.flatMap((x) => x.fields).map((f) => f.captured_at).sort().at(-1);
  return (
    <>
      <button ref={trigger} type="button" onClick={() => setOpen(true)} aria-expanded={open} aria-controls="ont-sidebar" data-testid="ont-sidebar-open"
        className="mt-3 inline-flex min-h-touch items-center rounded-btn border border-line px-3 text-sm hover:bg-bg">Configuração do aparelho</button>
      {open && (
        <aside id="ont-sidebar" ref={panel} tabIndex={-1} role="complementary" aria-labelledby="ont-sidebar-title" data-testid="ont-sidebar" onKeyDown={(e) => { if (e.key === "Escape") close(); }}
          className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-line bg-surface text-text shadow-card md:w-[420px]">
          <div className="flex items-start gap-3 border-b border-line p-4">
            <div className="shrink-0 text-muted"><DeviceThumbnail height={56} acs={form ? ((form.state === "fresh" ? "ok" : form.state === "no_data" ? "neutral" : "warn") as Tone) : "neutral"} /></div>
            <div className="min-w-0 flex-1">
              <h2 id="ont-sidebar-title" className="text-lg font-semibold">Configuração do aparelho</h2>
              <p className="truncate text-sm text-muted">{identity}</p>
              {form && <p className="mt-1 text-xs text-muted" data-testid="ont-sidebar-state">{STATE_TEXT[form.state]}{newest ? ` Última leitura ${ago(newest)}.` : ""}</p>}
            </div>
            <button type="button" onClick={close} data-testid="ont-sidebar-close" className="inline-flex min-h-touch min-w-touch items-center justify-center rounded-btn px-3 text-sm text-accent hover:underline">Recolher</button>
          </div>
          <div className="flex-1 overflow-y-auto p-4"><OntFormBody load={load} form={form} retry={retry} /></div>
        </aside>
      )}
    </>
  );
}
