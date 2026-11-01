import { expect, test } from "@playwright/test";
import { hasReading, indicatorSource, type QIndicator, type QMetric, valueText } from "../src/lib/quality";

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
