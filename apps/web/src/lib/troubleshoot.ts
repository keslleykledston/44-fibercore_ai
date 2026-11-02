import type { CustomerContext, CustomerOnu, DiagnosticFinding, Provenance, Rd004Finding } from "./types";

/** Rótulo de confiança de um passo: `confirmado` = fato medido e recente; `hipotese` = derivado de fatos, exige confirmação humana; `indisponivel` = dado velho/ausente, nada é afirmado. */
export type Trust = "confirmado" | "hipotese" | "indisponivel";
export type Step = { id: number; title: string; trust: Trust; summary: string; facts: [string, string][]; provenance: Provenance | null; action: { kind: "link" | "run"; label: string; href?: string } | null };
export const TRUST_LABEL: Record<Trust, { label: string; icon: string }> = {
  confirmado: { label: "Confirmado", icon: "●" }, hipotese: { label: "Hipótese", icon: "▲" }, indisponivel: { label: "Indisponível", icon: "○" },
};
const contract: Record<string, string> = { active: "ativo", suspended: "suspenso", cancelled: "cancelado", unknown: "não informado" };
const cause: Record<string, string> = { fiber_or_los: "suspeita de perda de sinal / fibra", power: "suspeita de falta de energia", unknown: "causa não determinada" };
/** Estados que a OLT realmente informa; qualquer outro valor (inclusive `unknown`) NÃO é lido como online nem como fora do ar. */
const UP = ["online"], DOWN = ["offline", "los", "dying_gasp"];
export const onuState = (status: string): "up" | "down" | "unrecognised" => (UP.includes(status) ? "up" : DOWN.includes(status) ? "down" : "unrecognised");
const stateText = (status: string) => ({ up: "online", down: "fora do ar", unrecognised: "em estado não reconhecido" })[onuState(status)];
const trustOf = (p: Provenance | null): Trust => (p && p.quality === "fresh" ? "confirmado" : "indisponivel");
const why = (p: Provenance | null) => (!p ? "sem coleta" : p.quality === "stale" ? "dado defasado" : p.quality === "conflict" ? "fontes divergentes" : p.quality === "unknown" ? "sem coleta" : "");

export type RunState = { finding: DiagnosticFinding | null; denied: boolean; failed: boolean; ranAt: string | null; discarded: "old" | "other_pon" | null };
export type RunState4 = { finding: Rd004Finding | null; denied: boolean; failed: boolean; ranAt: string | null; discarded: "old" | "other_onu" | null };
const CODE = /^[a-z_]{1,40}$/;
/** Lê o achado da R-D004 em formato fechado: qualquer outra forma (regra errada, campo fora do tipo) é recusada inteira e a tela afirma nada. */
export function readRd004(run: { rule_id: string; findings: unknown[] } | null): Rd004Finding | null {
  if (!run || run.rule_id !== "R-D004" || !Array.isArray(run.findings) || run.findings.length !== 1) return null;
  const f = run.findings[0] as Partial<Rd004Finding> | null;
  const e = f?.evidence as Partial<Rd004Finding["evidence"]> | undefined;
  if (!f || !e || !e.onu) return null;
  const okAge = e.inform_age_seconds === null || (typeof e.inform_age_seconds === "number" && Number.isInteger(e.inform_age_seconds) && e.inform_age_seconds >= 0);
  if (!["observed", "inferred", "unknown"].includes(String(f.status)) || typeof e.inform_fresh !== "boolean" || typeof e.snapshot_fresh !== "boolean" || !okAge
    || typeof e.onu.link !== "string" || typeof e.onu.fresh !== "boolean" || !(e.onu.status === null || (typeof e.onu.status === "string" && CODE.test(e.onu.status)))
    || typeof f.requires_human_confirmation !== "boolean") return null;
  return { status: f.status as Rd004Finding["status"], hypothesis: typeof f.hypothesis === "string" ? f.hypothesis : null, reason: typeof f.reason === "string" ? f.reason : undefined,
    suspected_cause: typeof f.suspected_cause === "string" && CODE.test(f.suspected_cause) ? f.suspected_cause : undefined, requires_human_confirmation: f.requires_human_confirmation,
    evidence: { onu: { link: e.onu.link, status: e.onu.status ?? null, fresh: e.onu.fresh }, inform_age_seconds: e.inform_age_seconds ?? null, inform_fresh: e.inform_fresh, snapshot_fresh: e.snapshot_fresh } };
}
const RD004_REASON: [string, string][] = [
  ["the CPE informed the ACS recently", "O roteador informou ao ACS recentemente."],
  ["the linked ONU is not online", "A ONU não está online na OLT: esta regra só vale para ONU online."],
  ["no confirmed ONU link", "Sem vínculo ONU↔roteador confirmado: a OLT e o ACS não podem ser comparados."],
  ["the ONU reading is too old", "A leitura da ONU está velha demais para comparar com o ACS."],
  ["no Inform time is known", "O ACS ainda não informou quando o roteador falou com ele pela última vez."],
  ["the CPE snapshot that carried the Inform time is itself old", "A coleta que trouxe a hora do último Inform está velha: o ACS pode já ter um Inform mais novo."],
];
const rd004Reason = (r?: string) => RD004_REASON.find(([k]) => r?.startsWith(k))?.[1] ?? "dado indisponível";
const informAge = (s: number | null) => (s === null ? "—" : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`);

/** Uma execução é um registro histórico: só vale como conclusão se for da PON atual da ONU e recente (mesma janela de frescor da regra). */
export const RUN_FRESH_MINUTES = 15;

/** Os 6 passos do diagnóstico guiado, só com o que a API já devolveu. Sem score, sem valor inventado. */
export function buildSteps(ctx: CustomerContext, onu: CustomerOnu | undefined, run: RunState, run4: RunState4, customerId: string, canRunHint: boolean): Step[] {
  const c = ctx.customer;
  const s1: Step = { id: 1, title: "Cliente e contrato", trust: trustOf(c.provenance), provenance: c.provenance,
    summary: trustOf(c.provenance) === "confirmado" ? `Contrato ${contract[c.contract_status] ?? contract.unknown}. Cadastro e contrato vêm do ERP e não comprovam conexão.` : `Cadastro com ${why(c.provenance)}: não use a situação do contrato como atual.`,
    facts: [["Contrato", contract[c.contract_status] ?? contract.unknown], ...(c.document_last4 ? [["Documento", `final ${c.document_last4}`] as [string, string]] : [])],
    action: { kind: "link", label: "Ver o cadastro na Visão 360", href: `/assinantes/${customerId}?aba=cliente` } };
  if (!onu) {
    const none = (id: number, title: string): Step => ({ id, title, trust: "indisponivel", provenance: null, summary: "Nenhuma ONU aprovada para este cliente: nada a verificar.", facts: [], action: id === 2 ? { kind: "link", label: "Aprovar o vínculo em Assinantes", href: "/assinantes" } : null });
    return [s1, none(2, "ONU aprovada"), none(3, "Estado e óptica da ONU"), none(4, "Padrão coletivo na PON"), none(5, "Roteador (CPE)"), none(6, "Sessão do roteador com o ACS")];
  }
  const s2: Step = { id: 2, title: "ONU aprovada", trust: "confirmado", provenance: null, summary: "Há uma ONU aprovada por uma pessoa para este cliente.",
    facts: [["Serial", onu.serial], ["OLT · PON", `${onu.olt}${onu.pon_path ? ` · ${onu.pon_path}` : ""}`]], action: { kind: "link", label: "Abrir a ONU 360", href: `/rede/onu/${onu.id}` } };
  const noState = onuState(onu.status) === "unrecognised" || onu.provenance.quality === "conflict";  // nothing is asserted about the state
  const t3: Trust = noState ? "indisponivel" : trustOf(onu.provenance);
  const s3: Step = { id: 3, title: "Estado e óptica da ONU", trust: t3, provenance: onu.provenance,
    summary: onu.provenance.quality === "conflict" ? "As fontes divergem sobre o estado desta ONU: nada é afirmado até serem conciliadas." : onuState(onu.status) === "unrecognised" ? "A OLT não informou um estado reconhecido para esta ONU: nada é afirmado." : t3 === "confirmado" ? `ONU ${stateText(onu.status)} na última leitura da OLT. Rx ausente não comprova a causa da queda.` : `Último estado conhecido (${why(onu.provenance)}): ${stateText(onu.status)}. A idade do dado não indica que a ONU esteja offline.`,
    facts: noState ? [] : [["Status", onu.status], ["Rx", onu.rx_dbm !== null ? `${onu.rx_dbm} dBm` : "—"]], action: { kind: "link", label: "Abrir a ONU 360", href: `/rede/onu/${onu.id}` } };
  const f = run.finding;
  const s4: Step = { id: 4, title: "Padrão coletivo na PON (R-D001)", provenance: null,
    trust: !f ? "indisponivel" : f.status === "inferred" ? "hipotese" : f.status === "observed" ? "confirmado" : "indisponivel",
    summary: run.denied ? "Seu papel não permite executar o diagnóstico." : run.failed ? "Não foi possível executar o diagnóstico agora; nada é afirmado." : !f ? (run.discarded === "old" ? "A última execução é antiga e foi descartada: ela não representa o estado atual. Execute de novo." : run.discarded === "other_pon" ? "A execução anterior era de outra PON e foi descartada. Execute de novo." : "Ainda não executado. A leitura não altera nada na rede.")
      : f.status === "inferred" ? `Hipótese: possível falha coletiva de acesso nesta PON (${cause[f.suspected_cause ?? "unknown"]}). Não é diagnóstico; confirme com o NOC/campo.`
      : f.status === "observed" ? "As quedas recentes não atingem o padrão de falha coletiva. Isso não prova que a PON esteja saudável." : `Sem conclusão: ${f.reason ?? "dado indisponível"}.`,
    facts: f ? [...(run.ranAt ? [["Executado em", run.ranAt] as [string, string]] : []), ["ONUs conhecidas na PON", String(f.evidence.onus_observed)], ["Caíram recentemente", String(f.evidence.onus_down_recent)], ["Online", String(f.evidence.online)], ["Cronicamente fora (não contam)", String(f.evidence.chronic_offline)]] : [],
    action: run.denied || !canRunHint ? null : { kind: "run", label: f ? "Reexecutar a leitura" : "Executar diagnóstico (somente leitura)" } };
  const k = onu.cpe;
  const s5: Step = { id: 5, title: "Roteador (CPE)", provenance: k.provenance,
    trust: k.link === "confirmed" ? trustOf(k.provenance) : k.link === "suggested" ? "hipotese" : "indisponivel",
    summary: k.link === "confirmed" ? (trustOf(k.provenance) === "confirmado" ? "Roteador vinculado e confirmado por uma pessoa. Identificar o roteador não comprova acesso à internet." : `Roteador confirmado, mas com ${why(k.provenance)}.`)
      : k.link === "suggested" ? "Há um roteador sugerido pelo serial igual: indício, não prova." : k.link === "unavailable" ? "O vínculo ONU↔CPE está desligado para este provedor." : "Nenhum roteador vinculado a esta ONU.",
    facts: k.device ? [["Equipamento", `${k.device.vendor ?? "—"} ${k.device.model ?? ""}`.trim()], ["Gerência", k.device.protocols.join(", ").toUpperCase() || "—"]] : [],
    action: { kind: "link", label: k.link === "suggested" ? "Revisar o vínculo na ONU 360" : "Abrir a ONU 360", href: `/rede/onu/${onu.id}` } };
  const g = run4.finding;
  const linked = k.link === "confirmed";
  const s6: Step = { id: 6, title: "Sessão do roteador com o ACS (R-D004)", provenance: null,
    trust: !linked || !g ? "indisponivel" : g.status === "inferred" ? "hipotese" : g.status === "observed" ? "confirmado" : "indisponivel",
    summary: !linked ? "Sem roteador confirmado para esta ONU: a sessão com o ACS não pode ser comparada com a OLT."
      : run4.denied ? "Seu papel não permite executar o diagnóstico." : run4.failed ? "Não foi possível executar a leitura agora; nada é afirmado."
      : !g ? (run4.discarded === "old" ? "A última execução é antiga e foi descartada: ela não representa o estado de agora. Execute de novo." : run4.discarded === "other_onu" ? "Essa execução é de outra ONU e foi ignorada." : "Ainda não executado. A leitura compara a ONU na OLT com o último contato do roteador com o ACS; nada é alterado.")
      : g.status === "inferred" ? "Hipótese: a ONU está online na OLT, mas o roteador não informou ao ACS recentemente. Aponta a sessão com o ACS (NAT, alcance, inform periódico), não prova que o cliente esteja sem internet. Confirme no ACS."
      : g.status === "observed" ? rd004Reason(g.reason) : `Sem conclusão: ${rd004Reason(g.reason)}`,
    facts: g ? [...(run4.ranAt ? [["Executado em", run4.ranAt] as [string, string]] : []), ["Estado da ONU na OLT", g.evidence.onu.status ?? "—"], ["Último Inform do roteador no ACS", g.evidence.inform_age_seconds === null ? "não informado" : `há ${informAge(g.evidence.inform_age_seconds)}`]] : [],
    action: !linked ? { kind: "link", label: "Abrir a ONU 360", href: `/rede/onu/${onu.id}` } : run4.denied || !canRunHint ? null : { kind: "run", label: g ? "Reexecutar a leitura" : "Executar leitura (somente leitura)" } };
  return [s1, s2, s3, s4, s5, s6];
}

export function conclusion(steps: Step[]): { trust: Trust; text: string } {
  const s4 = steps[3];
  if (s4.trust === "hipotese") return { trust: "hipotese", text: s4.summary };
  if (steps[5]?.trust === "hipotese") return { trust: "hipotese", text: steps[5].summary };
  if (s4.trust === "confirmado") return { trust: "confirmado", text: "Sem padrão coletivo na PON. Com os dados disponíveis a causa pode ser local ao cliente, mas isso não foi determinado." };
  return { trust: "indisponivel", text: "Sem conclusão: falta dado recente ou o diagnóstico ainda não foi executado." };
}

/** Texto do ticket: só o que a tela mostra, com a idade de cada dado. Nenhuma alteração foi feita na rede. */
const age = (p: Provenance, now: Date) => {
  if (!p.observed_at) return "idade indisponível";
  const m = Math.max(0, Math.floor((now.getTime() - Date.parse(p.observed_at)) / 60000));
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
};

export function ticketSummary(customerName: string, steps: Step[], c: { trust: Trust; text: string }, now: Date): string {
  const lines = [`Diagnóstico guiado — ${customerName}`, "Sintoma a investigar (premissa deste fluxo, não verificada): cliente sem conexão", `Gerado em ${now.toISOString()} (somente leitura; nenhuma alteração foi feita na rede).`, `Conclusão [${TRUST_LABEL[c.trust].label}]: ${c.text}`, ""];
  for (const s of steps) {
    lines.push(`${s.id}. ${s.title} [${TRUST_LABEL[s.trust].label}] — ${s.summary}`);
    for (const [k, v] of s.facts) if (k !== "Documento") lines.push(`   - ${k}: ${v}`);  // o documento (mesmo parcial) não é necessário ao ticket
    if (s.provenance) lines.push(`   - Fonte: ${s.provenance.source}; observado em ${s.provenance.observed_at ?? "sem coleta"} (${s.provenance.quality}; idade: ${age(s.provenance, now)})`);
  }
  return lines.join("\n");
}
