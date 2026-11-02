import { expect, test } from "@playwright/test";
import { rd003Lines, readRd003 } from "../src/lib/edgeDiagnostic";

// R-D003 no NOC (funções puras): o achado só é lido em formato fechado e o texto sai SÓ da evidência estruturada.
const ev = (o: Partial<{ heartbeat_age_seconds: number | null; silent: boolean; olts: number; onus_total: number; onus_not_fresh: number }> = {}) => ({ heartbeat_age_seconds: 7200, silent: true, olts: 1, onus_total: 10, onus_not_fresh: 10, ...o });
const run = (f: Record<string, unknown>, rule_id = "R-D003") => ({ rule_id, findings: [f] });
const finding = (e = ev(), o: Record<string, unknown> = {}) => ({ status: "inferred", hypothesis: "x", suspected_cause: "edge_unreachable", requires_human_confirmation: true, evidence: e, ...o });

test("achado válido é lido; regra errada, forma errada ou valor fora do tipo são recusados inteiros", () => {
  expect(readRd003(run(finding()))?.evidence).toEqual(ev());
  expect(readRd003(null)).toBeNull();
  expect(readRd003(run(finding(), "R-D004"))).toBeNull();
  expect(readRd003({ rule_id: "R-D003", findings: [] })).toBeNull();
  expect(readRd003({ rule_id: "R-D003", findings: [finding(), finding()] })).toBeNull();
  for (const bad of [ev({ silent: "yes" as never }), ev({ olts: -1 }), ev({ onus_total: 1.5 }), ev({ onus_not_fresh: 11 }), ev({ heartbeat_age_seconds: "7" as never }), ev({ onus_total: 10 ** 9 })]) {
    expect(readRd003(run(finding(bad)))).toBeNull();
  }
  expect(readRd003(run(finding(ev(), { status: "confirmed" })))).toBeNull();
  expect(readRd003(run(finding(ev(), { requires_human_confirmation: "no" })))).toBeNull();
  expect(readRd003(run({ status: "observed", requires_human_confirmation: false }))).toBeNull();
  expect(readRd003(run(finding(ev({ heartbeat_age_seconds: null }))))?.evidence.heartbeat_age_seconds).toBeNull();
});

test("causa suspeita só passa se for um código; texto livre da API não vira texto da tela", () => {
  expect(readRd003(run(finding(ev(), { suspected_cause: "edge_unreachable" })))?.suspected_cause).toBe("edge_unreachable");
  expect(readRd003(run(finding(ev(), { suspected_cause: "<script>alert(1)</script>" })))?.suspected_cause).toBeUndefined();
  const f = readRd003(run(finding(ev(), { hypothesis: "<img src=x onerror=alert(1)>" })))!;
  expect(JSON.stringify(rd003Lines(f))).not.toContain("onerror");
});

test("Edge silencioso: diz que pode ser dado velho, com a idade do último sinal e a contagem de leituras", () => {
  const t = rd003Lines(readRd003(run(finding()))!);
  expect(t.title).toBe("Edge sem sinal");
  expect(t.lines.join(" ")).toContain("há 2 h 0 min");
  expect(t.lines.join(" ")).toContain("As 10 leituras de ONU conhecidas estão velhas");
  expect(t.lines.join(" ")).toContain("pode ser só dado velho");
  const some = rd003Lines(readRd003(run(finding(ev({ onus_not_fresh: 4 }))))!);
  expect(some.lines.join(" ")).toContain("4 de 10 leituras de ONU estão velhas");
  const recent = rd003Lines(readRd003(run(finding(ev({ onus_not_fresh: 0 }))))!);
  expect(recent.lines.join(" ")).toContain("vão envelhecer sem nova coleta");
});

test("Edge reportando não afirma que as leituras estão atuais; sem ONU conhecida nada se diz delas", () => {
  const t = rd003Lines(readRd003(run(finding(ev({ silent: false, heartbeat_age_seconds: 40, onus_not_fresh: 2 }), { status: "observed", suspected_cause: undefined, requires_human_confirmation: false })))!);
  expect(t.title).toBe("Edge reportando");
  expect(t.lines.join(" ")).toContain("2 de 10 leituras de ONU estão velhas");
  expect(t.lines.join(" ")).toContain("não que as leituras da OLT estejam atuais");
  const none = rd003Lines(readRd003(run(finding(ev({ silent: false, onus_total: 0, onus_not_fresh: 0 }), { status: "observed", requires_human_confirmation: false })))!);
  expect(none.lines.join(" ")).toContain("Nenhuma ONU é conhecida");
});

test("sem conclusão: Edge revogado, nunca falou, ou dado indisponível", () => {
  const u = (reason: string) => rd003Lines(readRd003(run(finding(ev({ heartbeat_age_seconds: null, onus_total: 0, onus_not_fresh: 0 }), { status: "unknown", hypothesis: null, reason, requires_human_confirmation: false })))!);
  expect(u("this Edge was revoked: it is not expected to report")).toEqual({ title: "Sem conclusão", lines: ["Este Edge foi revogado: não se espera dado dele."] });
  expect(u("this Edge never sent a heartbeat: nothing is known about its collection").lines[0]).toContain("nunca enviou sinal");
  expect(u("anything else").lines[0]).toBe("Dado indisponível para concluir.");
});
