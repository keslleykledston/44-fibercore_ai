"use client";

import { useEffect, useRef, useState } from "react";
import { DeviceThumbnail, type Tone } from "@/components/DeviceThumbnail";
import { LOAD_ERROR, STATE_TEXT, readForm, valueText, type OntField, type OntForm, type OntGroup } from "@/lib/ont-config";

type Load = { kind: "idle" } | { kind: "loading" } | { kind: "ready"; cpe: string; form: OntForm } | { kind: "error"; error: string };
const TAB_LABEL: Record<string, string> = { resumo: "Resumo", wifi: "Wi-Fi", lan: "LAN", wan: "WAN" };
const ago = (iso: string) => {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 90 ? "agora há pouco" : s < 5400 ? `há ${Math.round(s / 60)} min` : s < 172800 ? `há ${Math.round(s / 3600)} h` : `há ${Math.round(s / 86400)} d`;
};

function FieldRow({ f }: { f: OntField }) {
  const id = `f-${f.name}-${f.instance_key}`.replace(/[^a-z0-9-]/gi, "-");
  return (
    <div className="grid gap-1" data-testid="ont-field">
      <label htmlFor={id} className="text-sm font-medium">{f.label}{f.quality === "stale" && <span className="ml-2 text-xs font-normal text-warn">defasado</span>}</label>
      <input id={id} readOnly value={valueText(f)} aria-readonly="true" aria-describedby={`${id}-why`} className="min-h-touch rounded-btn border border-line bg-bg px-3 text-sm text-text" />
      <p id={`${id}-why`} className="text-xs text-muted">{f.disabled_reason}</p>
    </div>
  );
}

function Fields({ group, instance }: { group: OntGroup; instance?: string }) {
  const fields = group.fields.filter((f) => !instance || f.instance_key === instance);
  if (fields.length === 0) return <p className="text-sm text-muted">Nada a mostrar aqui.</p>;
  return <div className="grid gap-4">{fields.map((f) => <FieldRow key={`${f.name}-${f.instance_key}`} f={f} />)}</div>;
}

/** Sidebar direito recolhível com a configuração do aparelho (SOMENTE LEITURA). Não é modal: a ONU 360 por trás continua navegável. Só mostra o que a API disse que foi observado. */
export function OntSidebar({ cpeId, identity }: { cpeId: string; identity: string }) {
  const [open, setOpen] = useState(false);
  const [load, setLoad] = useState<Load>({ kind: "idle" });
  const [attempt, setAttempt] = useState(0);   // 0 = ainda não pediu; cada "tentar de novo" soma 1 (não depende do estado de carga, senão o próprio efeito se cancela)
  const [tab, setTab] = useState("resumo");
  const [ssid, setSsid] = useState("");
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);

  useEffect(() => { setLoad({ kind: "idle" }); setTab("resumo"); setSsid(""); }, [cpeId]);   // outro aparelho: nada do anterior sobra

  useEffect(() => {
    if (!open || attempt === 0) return;
    let live = true;
    setLoad({ kind: "loading" });
    fetch(`/bff/cpes/${cpeId}/ont-config`, { cache: "no-store" }).then(async (r) => {
      const j = (await r.json().catch(() => ({}))) as { form?: unknown; error?: string };
      if (!live) return;
      const form = r.ok ? readForm(j.form) : null;
      if (form) { setLoad({ kind: "ready", cpe: cpeId, form }); setSsid(form.instances.ssid[0]?.key ?? ""); }
      else setLoad({ kind: "error", error: j.error && LOAD_ERROR[j.error] ? j.error : "failed" });
    }).catch(() => live && setLoad({ kind: "error", error: "failed" }));
    return () => { live = false; };
  }, [open, attempt, cpeId]);

  useEffect(() => { if (open) panel.current?.focus(); }, [open]);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  const form = load.kind === "ready" && load.cpe === cpeId ? load.form : null;   // uma leitura só vale para o aparelho que a pediu
  const g = (id: string) => form?.groups.find((x) => x.id === id);
  const tabs = ["resumo", ...(g("wifi") ? ["wifi"] : []), ...(g("lan") ? ["lan"] : []), ...(g("wan") ? ["wan"] : [])];
  const active = tabs.includes(tab) ? tab : "resumo";
  const newest = form?.groups.flatMap((x) => x.fields).map((f) => f.captured_at).sort().at(-1);

  return (
    <>
      <button ref={trigger} type="button" onClick={() => { setOpen(true); setAttempt((n) => (n === 0 ? 1 : n)); }} aria-expanded={open} aria-controls="ont-sidebar" data-testid="ont-sidebar-open"
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
          <div className="flex-1 overflow-y-auto p-4">
            {load.kind === "loading" && <p className="text-sm text-muted">Carregando a configuração…</p>}
            {load.kind === "error" && (
              <div role="alert" data-testid="ont-sidebar-error" className="grid gap-3 text-sm">
                <p className="text-danger">{LOAD_ERROR[load.error] ?? LOAD_ERROR.failed}</p>
                {load.error === "failed" && <button type="button" onClick={() => setAttempt((n) => n + 1)} className="min-h-touch w-fit rounded-btn border border-line px-3">Tentar de novo</button>}
              </div>
            )}
            {form && (
              <div className="grid gap-4">
                {form.synthetic && <p role="note" data-testid="ont-synthetic" className="rounded-btn border border-line bg-bg p-3 text-sm">Dados <strong>sintéticos</strong> de demonstração: não vieram do aparelho.</p>}
                <p role="note" className="rounded-btn border border-line bg-bg p-3 text-sm text-muted">Somente leitura. A edição só será liberada depois de pré-visualização, aprovação e homologação deste modelo e firmware.</p>
                {form.groups.length === 0 ? (
                  <div data-testid="ont-no-capability" className="grid gap-2 text-sm">
                    <p className="font-medium">Nenhuma capacidade foi lida deste aparelho.</p>
                    <p className="text-muted">Quando a gerência remota informar a configuração, ela aparece aqui. Para liberar este modelo, peça a homologação à engenharia.</p>
                  </div>
                ) : (
                  <>
                    <div role="tablist" aria-label="Seções" className="flex flex-wrap gap-1">
                      {tabs.map((t) => (
                        <button key={t} role="tab" type="button" id={`ont-tab-${t}`} aria-selected={active === t} aria-controls={`ont-panel-${t}`} onClick={() => setTab(t)}
                          className={`min-h-touch rounded-btn px-3 text-sm ${active === t ? "bg-accent text-[color:var(--on-accent)]" : "border border-line hover:bg-bg"}`}>{TAB_LABEL[t]}</button>
                      ))}
                    </div>
                    <div role="tabpanel" id={`ont-panel-${active}`} aria-labelledby={`ont-tab-${active}`} className="grid gap-4">
                      {active === "resumo" && (
                        <>
                          {g("optical") && (
                            <section aria-labelledby="ont-optical" data-testid="ont-optical" className="grid gap-3">
                              <h3 id="ont-optical" className="text-sm font-semibold">Óptica <span className="font-normal text-muted">· somente leitura</span></h3>
                              <Fields group={g("optical")!} />
                            </section>
                          )}
                          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                            <dt className="text-muted">Fabricante</dt><dd>{form.fingerprint.vendor ?? "—"}</dd>
                            <dt className="text-muted">Modelo</dt><dd>{form.fingerprint.model ?? "—"}</dd>
                            <dt className="text-muted">Firmware</dt><dd>{form.fingerprint.firmware ?? "—"}</dd>
                            <dt className="text-muted">Redes Wi-Fi</dt><dd>{form.instances.ssid.length || "—"}</dd>
                          </dl>
                        </>
                      )}
                      {active === "wifi" && g("wifi") && (
                        <>
                          {form.instances.ssid.length > 1 && (
                            <div className="grid gap-1">
                              <label htmlFor="ont-ssid-picker" className="text-sm font-medium">Rede</label>
                              <select id="ont-ssid-picker" value={ssid} onChange={(e) => setSsid(e.target.value)} className="min-h-touch rounded-btn border border-line bg-bg px-3 text-sm">
                                {form.instances.ssid.map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
                              </select>
                            </div>
                          )}
                          <Fields group={{ ...g("wifi")!, fields: g("wifi")!.fields.filter((f) => !f.instance_key.startsWith("ssid/") || f.instance_key === ssid) }} />
                        </>
                      )}
                      {active === "lan" && g("lan") && <Fields group={g("lan")!} />}
                      {active === "wan" && g("wan") && <Fields group={g("wan")!} />}
                    </div>
                  </>
                )}
                <p className="text-xs"><a href={`/ajuda/${form.help_slug}`} className="text-accent underline underline-offset-2" data-testid="ont-help">Como ler esta configuração</a></p>
                <p className="text-xs text-muted">Revisão da leitura <span className="font-mono">{form.form_revision}</span>. Senhas nunca são mostradas.</p>
              </div>
            )}
          </div>
        </aside>
      )}
    </>
  );
}
