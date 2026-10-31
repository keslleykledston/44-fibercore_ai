"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { DeviceThumbnail } from "@/components/DeviceThumbnail";
import { EntityDetailDrawer } from "@/components/EntityDetailDrawer";
import { readQuick, type QuickModel } from "@/lib/onu-quick";
import type { Onu } from "@/lib/types";

type State = { id: string; kind: "loading" } | { id: string; kind: "ready"; model: QuickModel } | { id: string; kind: "error"; code: string };
const ERR: Record<string, string> = {
  forbidden: "Seu papel não permite ver o inventário.", not_found: "Esta ONU não existe mais.", session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  failed: "Não foi possível carregar o resumo",
};
const TONE_CLASS: Record<string, string> = { ok: "text-ok", warn: "text-warn", bad: "text-danger", neutral: "text-text" };
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : null);

function useWide() {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const m = window.matchMedia("(min-width: 1024px)");
    const f = () => setWide(m.matches);
    f(); m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);
  return wide;
}

function Line({ k, children }: { k: string; children: ReactNode }) {
  return <div className="grid gap-0.5"><dt className="text-xs text-muted">{k}</dt><dd className="text-sm">{children}</dd></div>;
}

function Body({ row, state, oltName, retry }: { row: Onu; state: State | null; oltName: string; retry: () => void }) {
  const m = state && state.id === row.id && state.kind === "ready" ? state.model : null;   // nunca mostra o resumo de OUTRA ONU como se fosse esta
  return (
    <div className="grid gap-4" data-testid="onu-quick-body">
      <div className="flex justify-center"><DeviceThumbnail pon={m?.pon.tone ?? "neutral"} acs={m?.acs.tone ?? "neutral"} /></div>
      <p className="-mt-2 text-center text-xs text-muted">Representação genérica do dispositivo. Os pontos de luz mostram a PON e o ACS, não os LEDs reais.</p>
      {state?.id === row.id && state.kind === "error" && (
        <div role="alert" data-testid="onu-quick-error" className="grid gap-2 text-sm">
          <p className="text-danger">{ERR[state.code] ?? ERR.failed}</p>
          {state.code === "failed" && <button type="button" onClick={retry} className="min-h-touch w-fit rounded-btn border border-line px-3">Tentar novamente</button>}
        </div>
      )}
      {!m && state?.id === row.id && state.kind === "loading" && <p className="text-sm text-muted" data-testid="onu-quick-loading">Carregando o resumo…</p>}
      <dl className="grid gap-3">
        <Line k="OLT / PON">{m ? `${m.onu.olt_name} · ${m.onu.pon_ref ?? "—"}` : `${oltName} · ${row.pon_path ?? "—"}`}{m?.onu.olt_vendor_model ? <span className="block text-xs text-muted">{m.onu.olt_vendor_model}</span> : null}</Line>
        {m && (
          <>
            <Line k="Registro PON"><span className={`font-medium ${TONE_CLASS[m.pon.tone]}`}>{m.pon.label}</span>
              {m.pon.detail && <span className="block text-xs text-muted">{m.pon.detail}</span>}
              <span className="block text-xs text-muted">Origem: OLT{when(m.pon.observed_at) ? ` · observado em ${when(m.pon.observed_at)}` : " · sem coleta recente"}</span></Line>
            <Line k="Comunicação ACS"><span className={`font-medium ${TONE_CLASS[m.acs.tone]}`}>{m.acs.label}</span>
              {m.acs.vendor_model && <span className="block text-xs text-muted">{m.acs.vendor_model}</span>}
              {m.acs.source && <span className="block text-xs text-muted">Origem: ACS{when(m.acs.observed_at) ? ` · observado em ${when(m.acs.observed_at)}` : ""}</span>}</Line>
            <Line k="Potência recebida"><span className="font-medium">{m.optical.label}</span>
              <span className="block text-xs text-muted">{m.optical.rx_dbm === null ? "Sem medição." : `Origem: OLT · sem limiar homologado, por isso sem cor de severidade.`}</span></Line>
            <Line k="Cliente"><span className="font-medium" data-testid="onu-quick-customer">{m.association.customer ?? m.association.label}</span>
              {m.association.customer && <span className="block text-xs text-muted">{m.association.label}</span>}</Line>
          </>
        )}
        <Line k="Status e frescor"><span className="text-xs text-muted">{row.freshness === "fresh" ? "Dado recente" : row.freshness === "stale" ? "Dados defasados" : "Sem coleta"}{when(row.observed_at) ? ` · última coleta em ${when(row.observed_at)}` : ""}</span></Line>
      </dl>
      <Link href={`/rede/onu/${row.id}`} data-testid="onu-360-link" className="inline-flex min-h-touch items-center justify-center rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">Abrir Visão 360°</Link>
      <Link href="/ajuda/rede/consultar-onu" className="text-xs text-accent underline underline-offset-2">Como consultar uma ONU</Link>
    </div>
  );
}

/** Resumo da ONU selecionada (UX 2.2). Largo (≥1024 px): painel direito NÃO modal, a lista continua navegável; estreito: gaveta modal. Trocar a ONU mantém o painel e nunca mostra o resumo da anterior. */
export function OnuQuickInspector({ row, oltName, onClose }: { row: Onu | null; oltName: string; onClose: () => void }) {
  const wide = useWide();
  const [state, setState] = useState<State | null>(null);
  const [tries, setTries] = useState(0);
  const panel = useRef<HTMLElement>(null);
  const opened = useRef(false);
  const id = row?.id ?? null;

  useEffect(() => {
    if (!id) { setState(null); return; }
    const ctl = new AbortController();
    setState({ id, kind: "loading" });
    fetch(`/bff/onus/${id}/quick`, { cache: "no-store", signal: ctl.signal }).then(async (r) => {
      const j = (await r.json().catch(() => ({}))) as { model?: unknown; error?: string };
      const model = r.ok ? readQuick(j.model) : null;
      setState(model ? { id, kind: "ready", model } : { id, kind: "error", code: j.error && ERR[j.error] ? j.error : "failed" });
    }).catch((e) => { if ((e as Error).name !== "AbortError") setState({ id, kind: "error", code: "failed" }); });
    return () => ctl.abort();   // trocar de ONU cancela o pedido da anterior
  }, [id, tries]);

  useEffect(() => {   // Esc fecha o painel não modal mesmo com o foco na lista (a gaveta modal trata o Esc sozinha)
    if (!row || !wide) return;
    const f = (e: KeyboardEvent) => { if (e.key === "Escape" && !document.querySelector("dialog[open]")) onClose(); };
    document.addEventListener("keydown", f);
    return () => document.removeEventListener("keydown", f);
  }, [row, wide, onClose]);

  useEffect(() => {
    if (row && wide && !opened.current) panel.current?.focus();
    opened.current = row !== null;
  }, [row, wide]);

  if (!row) return null;
  const body = <Body row={row} state={state} oltName={oltName} retry={() => setTries((n) => n + 1)} />;
  if (!wide) return <EntityDetailDrawer open onClose={onClose} title={`ONU ${row.serial}`}><div data-testid="onu-quick" data-mode="sheet">{body}</div></EntityDetailDrawer>;
  const m = state?.id === row.id && state.kind === "ready" ? state.model : null;
  return (
    <aside ref={panel} tabIndex={-1} role="complementary" aria-labelledby="onu-quick-title" data-testid="onu-quick" data-mode="panel" onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
      className="fixed inset-y-0 right-0 z-30 flex w-[400px] max-w-full flex-col border-l border-line bg-surface text-text shadow-card">
      <div className="sticky top-0 flex items-start justify-between gap-3 border-b border-line bg-surface p-4">
        <div className="min-w-0">
          <p className="text-xs text-muted">Resumo da ONU</p>
          <h2 id="onu-quick-title" className="truncate font-mono text-lg font-semibold">{row.serial}</h2>
          {m && <p className={`text-sm font-medium ${TONE_CLASS[m.pon.tone]}`}>{m.pon.label}</p>}
        </div>
        <button type="button" onClick={onClose} data-testid="onu-quick-close" aria-label="Fechar detalhes" className="inline-flex min-h-touch min-w-touch items-center justify-center rounded-btn px-3 text-sm text-accent hover:underline">Fechar detalhes</button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">{body}</div>
    </aside>
  );
}
