"use client";

import { useEffect, useState } from "react";
import { LOAD_ERROR, readForm, valueText, type OntField, type OntForm, type OntGroup } from "@/lib/ont-config";

export type Load = { kind: "idle" } | { kind: "loading" } | { kind: "ready"; cpe: string; form: OntForm } | { kind: "error"; error: string };
const TAB_LABEL: Record<string, string> = { resumo: "Resumo", wifi: "Wi-Fi", lan: "LAN", wan: "WAN" };
export const ago = (iso: string) => {
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

/** Leitura da configuração de UM aparelho (BFF → API, somente leitura). `on` liga a busca; `attempt` 0 = ainda não pediu (cada "tentar de novo" soma 1: não depende do estado de carga, senão o próprio efeito se cancela).
 *  Uma leitura só vale para o aparelho que a pediu (`form` é nulo se o estado é de outro `cpeId`). */
export function useOntForm(cpeId: string, on: boolean) {
  const [load, setLoad] = useState<Load>({ kind: "idle" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => { setLoad({ kind: "idle" }); setAttempt(0); }, [cpeId]);   // outro aparelho: nada do anterior sobra
  useEffect(() => { if (on) setAttempt((n) => (n === 0 ? 1 : n)); }, [on, cpeId]);
  useEffect(() => {
    if (!on || attempt === 0) return;
    let live = true;
    setLoad({ kind: "loading" });
    fetch(`/bff/cpes/${cpeId}/ont-config`, { cache: "no-store" }).then(async (r) => {
      const j = (await r.json().catch(() => ({}))) as { form?: unknown; error?: string };
      if (!live) return;
      const form = r.ok ? readForm(j.form) : null;
      if (form) setLoad({ kind: "ready", cpe: cpeId, form });
      else setLoad({ kind: "error", error: j.error && LOAD_ERROR[j.error] ? j.error : "failed" });
    }).catch(() => live && setLoad({ kind: "error", error: "failed" }));
    return () => { live = false; };
  }, [on, attempt, cpeId]);
  const form = load.kind === "ready" && load.cpe === cpeId ? load.form : null;
  return { load, form, retry: () => setAttempt((n) => n + 1) };
}

/** Estado, erro e formulários (abas Resumo/Wi-Fi/LAN/WAN). Compartilhado pelo sidebar da ONU 360° e pelo painel de gestão da lista. */
export function OntFormBody({ load, form, retry }: { load: Load; form: OntForm | null; retry: () => void }) {
  const [tab, setTab] = useState("resumo");
  const [ssid, setSsid] = useState("");
  useEffect(() => { setSsid((cur) => (form && form.instances.ssid.some((i) => i.key === cur) ? cur : form?.instances.ssid[0]?.key ?? "")); }, [form]);
  const g = (id: string) => form?.groups.find((x) => x.id === id);
  const tabs = ["resumo", ...(g("wifi") ? ["wifi"] : []), ...(g("lan") ? ["lan"] : []), ...(g("wan") ? ["wan"] : [])];
  const active = tabs.includes(tab) ? tab : "resumo";
  return (
    <>
      {load.kind === "loading" && <p className="text-sm text-muted">Carregando a configuração…</p>}
      {load.kind === "error" && (
        <div role="alert" data-testid="ont-sidebar-error" className="grid gap-3 text-sm">
          <p className="text-danger">{LOAD_ERROR[load.error] ?? LOAD_ERROR.failed}</p>
          {load.error === "failed" && <button type="button" onClick={retry} className="min-h-touch w-fit rounded-btn border border-line px-3">Tentar de novo</button>}
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
    </>
  );
}
