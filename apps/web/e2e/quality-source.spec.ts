import { expect, test } from "@playwright/test";
import { hasReading, indicatorDisplay, indicatorSource, metricAgeSuffix, metricStatusText, type QIndicator, type QMetric, valueText } from "../src/lib/quality";

// "Fonte · idade" de cada indicador da Qualidade (funções puras, sem navegador nem API).
const M = (over: Partial<QMetric>): QMetric => ({
  id: "wan.link_status", group: "WAN", status: "valid", value: "Up", unit: null, source: "ACS_CACHE", scope: "SERVICE_WAN", instance: null,
  collected_at: "2026-11-01T12:00:00Z", freshness_s: 30, judged: null, ...over,
});
const IND = (ids: string[]): QIndicator => ({ state: "ok", metric_ids: ids });

test("sem métrica com leitura o indicador diz 'sem leitura', nunca uma fonte inventada", () => {
  expect(indicatorSource(IND([]), [M({})])).toBe("Fonte: sem leitura");
  expect(indicatorSource(IND(["wan.link_status"]), [M({ status: "not_available" })])).toBe("Fonte: sem leitura");
  expect(indicatorSource(IND(["wan.link_status"]), [M({ status: "failed" }), M({ status: "not_supported" })])).toBe("Fonte: sem leitura");
});

test("métrica válida ou antiga SEM valor não conta como leitura: não ganha fonte nem idade", () => {
  expect(indicatorSource(IND(["wan.link_status"]), [M({ status: "valid", value: null })])).toBe("Fonte: sem leitura");
  expect(indicatorSource(IND(["wan.link_status"]), [M({ status: "stale", value: null })])).toBe("Fonte: sem leitura");
  const ms = [M({ id: "wan.link_status", value: null, freshness_s: 5 }), M({ id: "wan.connection_status", source: "TR069_READ", freshness_s: 120 })];
  expect(indicatorSource(IND(["wan.link_status", "wan.connection_status"]), ms)).toBe("Fonte: ACS (leitura) · há 2 min");   // só a métrica com valor entra
});

test("texto vazio ou só espaços também não é leitura, mas 0 e false são", () => {
  for (const value of ["", "   "]) {
    expect(indicatorSource(IND(["wan.link_status"]), [M({ value })]), JSON.stringify(value)).toBe("Fonte: sem leitura");
    expect(valueText(M({ value })), JSON.stringify(value)).toBe("—");
  }
  expect(hasReading(M({ value: 0 }))).toBe(true);
  expect(hasReading(M({ value: false }))).toBe(true);
  expect(indicatorSource(IND(["wan.link_status"]), [M({ value: 0 })])).toBe("Fonte: ACS (cache) · agora há pouco");
  expect(valueText(M({ value: false }))).toBe("Não");
});

test("uma métrica: fonte em palavras e a idade dela", () => {
  expect(indicatorSource(IND(["optical.rx_dbm"]), [M({ id: "optical.rx_dbm", source: "OLT_ADAPTER", freshness_s: 120 })])).toBe("Fonte: OLT · há 2 min");
  expect(indicatorSource(IND(["wan.link_status"]), [M({ freshness_s: 30 })])).toBe("Fonte: ACS (cache) · agora há pouco");
  expect(indicatorSource(IND(["wan.link_status"]), [M({ status: "stale", freshness_s: 7200 })])).toBe("Fonte: ACS (cache) · há 2 h");
});

test("várias métricas: a idade é a da MAIS ANTIGA e as fontes aparecem sem repetir", () => {
  const ms = [M({ id: "wan.link_status", freshness_s: 30 }), M({ id: "wan.connection_status", source: "TR069_READ", freshness_s: 7200 }), M({ id: "cpe.uptime_s", freshness_s: 10 })];
  expect(indicatorSource(IND(["wan.link_status", "wan.connection_status"]), ms)).toBe("Fonte: ACS (cache) + ACS (leitura) · a mais antiga há 2 h");
  expect(indicatorSource(IND(["wan.link_status", "cpe.uptime_s"]), ms)).toBe("Fonte: ACS (cache) · a mais antiga agora há pouco");
});

test("uma leitura sem idade conhecida nunca fica escondida atrás da idade das outras", () => {
  expect(indicatorSource(IND(["wan.link_status"]), [M({ freshness_s: null })])).toBe("Fonte: ACS (cache) · idade desconhecida");
  const ms = [M({ id: "wan.link_status", freshness_s: 30 }), M({ id: "wan.connection_status", status: "stale", freshness_s: null })];
  expect(indicatorSource(IND(["wan.link_status", "wan.connection_status"]), ms)).toBe("Fonte: ACS (cache) · idade desconhecida");
});

test("métricas fora do indicador e fonte desconhecida não vazam para a linha", () => {
  expect(indicatorSource(IND(["wan.link_status"]), [M({ id: "optical.rx_dbm", source: "OLT_ADAPTER" })])).toBe("Fonte: sem leitura");
  expect(indicatorSource(IND(["wan.link_status"]), [M({ source: "NOVA_FONTE" })])).toBe("Fonte: outra fonte · agora há pouco");
});

test("métrica valid/stale sem valor não é 'Leitura atual/antiga' nem ganha idade nos detalhes", () => {
  for (const status of ["valid", "stale"] as const) {
    const m = M({ status, value: "", freshness_s: 30 });
    expect(metricStatusText(m)).toBe("Sem leitura");
    expect(metricAgeSuffix(m)).toBe("");
  }
  expect(metricStatusText(M({ status: "valid", value: "Up" }))).toBe("Leitura atual");
  expect(metricAgeSuffix(M({ status: "valid", value: "Up", freshness_s: 30 }))).toBe(" · agora há pouco");
  expect(metricStatusText(M({ status: "stale", value: 0, freshness_s: 7200 }))).toBe("Leitura antiga");
  expect(metricStatusText(M({ status: "not_available" }))).toBe("Sem leitura");
});

test("o cartão do indicador só diz 'ok' ou 'Leitura atual, sem faixa' quando há leitura de verdade", () => {
  const ok = (ids: string[]): QIndicator => ({ state: "ok", metric_ids: ids });
  const rx = (over: Partial<QMetric>) => M({ id: "optical.rx_dbm", group: "OPTICAL", source: "OLT_ADAPTER", value: -18.75, unit: "dBm", ...over });
  // sem leitura (valor vazio): nada de "ok" nem de "Leitura atual"
  expect(indicatorDisplay("optical", ok(["optical.rx_dbm"]), [rx({ value: "" })])).toEqual({ state: "unknown", text: "Sem leitura" });
  expect(indicatorDisplay("wan", ok(["wan.link_status"]), [M({ value: "   " })])).toEqual({ state: "unknown", text: "Sem leitura" });
  // com leitura, mas sem faixa homologada (judged não é true)
  expect(indicatorDisplay("optical", ok(["optical.rx_dbm"]), [rx({})]).state).toBe("unjudged");
  expect(indicatorDisplay("optical", ok(["optical.rx_dbm"]), [rx({ judged: true })])).toEqual({ state: "ok", text: "Sem anomalia observada" });
  // um "judged" sem valor não conta
  expect(indicatorDisplay("optical", ok(["optical.rx_dbm"]), [rx({ judged: true, value: "" })]).state).toBe("unknown");
  // outros estados passam como a API disse
  expect(indicatorDisplay("wan", { state: "attention", metric_ids: ["wan.link_status"] }, [M({})])).toEqual({ state: "attention", text: "Atenção" });
  expect(indicatorDisplay("wifi", { state: "unknown", metric_ids: [] }, [])).toEqual({ state: "unknown", text: "Sem leitura" });
});
