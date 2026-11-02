import type { Rd003Finding } from "./types";

const CODE = /^[a-z_]{1,40}$/;
const isCount = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0 && v <= 10_000_000;

/** Lê o achado da R-D003 em formato fechado: qualquer outra forma (regra errada, campo fora do tipo) é recusada inteira e a tela não afirma nada. */
export function readRd003(run: { rule_id: string; findings: unknown[] } | null): Rd003Finding | null {
  if (!run || run.rule_id !== "R-D003" || !Array.isArray(run.findings) || run.findings.length !== 1) return null;
  const f = run.findings[0] as Partial<Rd003Finding> | null;
  const e = f?.evidence as Partial<Rd003Finding["evidence"]> | undefined;
  if (!f || !e) return null;
  const okAge = e.heartbeat_age_seconds === null || isCount(e.heartbeat_age_seconds);
  if (!["observed", "inferred", "unknown"].includes(String(f.status)) || !okAge || typeof e.silent !== "boolean" || !isCount(e.olts) || !isCount(e.onus_total) || !isCount(e.onus_not_fresh)
    || e.onus_not_fresh > e.onus_total || typeof f.requires_human_confirmation !== "boolean") return null;
  return {
    status: f.status as Rd003Finding["status"], hypothesis: typeof f.hypothesis === "string" ? f.hypothesis : null, reason: typeof f.reason === "string" ? f.reason : undefined,
    suspected_cause: typeof f.suspected_cause === "string" && CODE.test(f.suspected_cause) ? f.suspected_cause : undefined, requires_human_confirmation: f.requires_human_confirmation,
    evidence: { heartbeat_age_seconds: e.heartbeat_age_seconds ?? null, silent: e.silent, olts: e.olts, onus_total: e.onus_total, onus_not_fresh: e.onus_not_fresh },
  };
}

const age = (s: number | null) => (s === null ? "—" : s < 3600 ? `${Math.floor(s / 60)} min` : s < 172800 ? `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min` : `${Math.floor(s / 86400)} dias`);

/** O texto do achado em português, montado SÓ da evidência estruturada (e do motivo para os dois casos sem evidência): nunca repete texto livre que veio da API. */
export function rd003Lines(f: Rd003Finding): { title: string; lines: string[] } {
  const e = f.evidence;
  if (f.status === "unknown") {
    const why = f.reason?.startsWith("this Edge was revoked") ? "Este Edge foi revogado: não se espera dado dele."
      : f.reason?.startsWith("this Edge never sent a heartbeat") ? "Este Edge nunca enviou sinal: nada se sabe sobre a coleta dele." : "Dado indisponível para concluir.";
    return { title: "Sem conclusão", lines: [why] };
  }
  const data = e.onus_total === 0 ? "Nenhuma ONU é conhecida nas OLTs deste Edge."
    : e.onus_not_fresh === 0 ? `As ${e.onus_total} leituras de ONU conhecidas ainda são recentes${e.silent ? ", mas vão envelhecer sem nova coleta" : ""}.`
    : e.onus_not_fresh === e.onus_total ? `As ${e.onus_total} leituras de ONU conhecidas estão velhas.` : `${e.onus_not_fresh} de ${e.onus_total} leituras de ONU estão velhas.`;
  if (e.silent) {
    return { title: "Edge sem sinal", lines: [`Último sinal há ${age(e.heartbeat_age_seconds)}; ${e.olts} OLT(s) dependem dele.`, data,
      "Uma ONU que parece offline atrás deste Edge pode ser só dado velho: não trate como queda. Verifique o host do Edge e o enlace dele com a nuvem."] };
  }
  return { title: "Edge reportando", lines: [`Sinal recente (há ${age(e.heartbeat_age_seconds)}); ${e.olts} OLT(s).`, data,
    "O sinal prova que o processo do Edge está vivo, não que as leituras da OLT estejam atuais: o que conta é a idade das leituras acima."] };
}
