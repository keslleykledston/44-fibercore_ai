import { expect, test } from "@playwright/test";
import { indicatorSource, type QIndicator, type QMetric } from "../src/lib/quality";

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
