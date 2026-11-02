import { expect, test } from "@playwright/test";
import { buildPanel, ponCapacityOf, type BoardsResult } from "../src/lib/oltPanel";
import type { Onu } from "../src/lib/types";

// Regras do painel da MA5608T (funções puras: sem navegador nem API). Cobrem os cenários dos critérios de aceite do pacote.
const onu = (pon: string, status: string, freshness = "fresh", i = Math.random()): Onu => ({ id: String(i), olt_id: "o", serial: `S${i}`, pon_path: pon, status, rx_dbm: -20, observed_at: null, freshness });
const boards = (slots: [number, string][], empty: number[] = [], stale = false): BoardsResult => ({ boards: slots.map(([slot, name]) => ({ slot, name, status: "Normal" })), empty_slots: empty, observedAt: "2026-11-02T12:00:00Z", stale });
const fresh = { freshness: "fresh" };
const port = (m: ReturnType<typeof buildPanel>, s: number, p: number) => m.slots[s]!.ports.find((x) => x.port === p)!;

test("dois cartões GPFD presentes: 16 portas em cada um, com a chave F/S/P exata", () => {
  const m = buildPanel(fresh, [], boards([[0, "H805GPFD"], [1, "H805GPFD"]]));
  expect(m.slots.map((s) => [s.slot, s.presence, s.ponCapacity, s.ports.length])).toEqual([[0, "present", 16, 16], [1, "present", 16, 16]]);
  expect(m.slots[1]!.ports.map((p) => p.key)).toEqual(Array.from({ length: 16 }, (_, i) => `0/1/${i}`));
});

test("só o slot 0 ou só o slot 1; vazio só quando o inventário constata", () => {
  const a = buildPanel(fresh, [], boards([[0, "H805GPFD"]], [1]));
  expect([a.slots[0]!.presence, a.slots[1]!.presence, a.slots[1]!.ports.length]).toEqual(["present", "empty", 0]);
  const b = buildPanel(fresh, [], boards([[1, "H805GPFD"]], [0]));
  expect([b.slots[0]!.presence, b.slots[1]!.presence, b.slots[0]!.ports.length, b.slots[1]!.ports.length]).toEqual(["empty", "present", 0, 16]);
});

test("inventário não lido NÃO vira slot vazio nem portas inventadas; ONU coletada prova que a placa existe, mas sem modelo não há 16 portas", () => {
  const none = buildPanel(fresh, [], null);
  expect(none.slots.map((s) => [s.presence, s.evidence, s.ports.length])).toEqual([["unknown", "none", 0], ["unknown", "none", 0]]);
  const seen = buildPanel(fresh, [onu("0/0/3", "online")], null);
  expect([seen.slots[0]!.presence, seen.slots[0]!.evidence, seen.slots[0]!.supported, seen.slots[0]!.ports.length, seen.slots[1]!.presence]).toEqual(["present", "onu_data", false, 0, "unknown"]);
});

test("modelo de placa: GPFD=16, GPBD=8, desconhecido (XG-PON, outro) sem template", () => {
  expect([ponCapacityOf("H805GPFD"), ponCapacityOf("H802GPBD"), ponCapacityOf("H901XGBD"), ponCapacityOf(null)]).toEqual([16, 8, null, null]);
  const m = buildPanel(fresh, [], boards([[0, "H802GPBD"], [1, "H901XGBD"]]));
  expect([m.slots[0]!.ports.length, m.slots[1]!.supported, m.slots[1]!.ports.length, m.slots[1]!.boardModel]).toEqual([8, false, 0, "H901XGBD"]);
});

test("a ONU entra na porta pela chave exata (não pela posição): 0/1/3 não aparece em 0/0/3", () => {
  const m = buildPanel(fresh, [onu("0/1/3", "online"), onu("0/1/3", "offline"), onu("0/0/4", "online")], boards([[0, "H805GPFD"], [1, "H805GPFD"]]));
  expect(port(m, 1, 3).onus).toEqual({ online: 1, offline: 1, total: 2 });
  expect(port(m, 0, 3).onus).toEqual({ online: 0, offline: 0, total: 0 });
  expect(port(m, 0, 4).onus.online).toBe(1);
});

test("LED: UP só com ONU online provando a porta e nenhuma fora; PON UP com ONU fora é ATENÇÃO e continua operacional UP", () => {
  const m = buildPanel(fresh, [onu("0/0/0", "online"), onu("0/0/1", "online"), onu("0/0/1", "offline"), onu("0/0/2", "offline"), onu("0/0/2", "los")], boards([[0, "H805GPFD"]]));
  expect([port(m, 0, 0).led, port(m, 0, 0).operational, port(m, 0, 0).operationalSource]).toEqual(["up", "up", "onu_online"]);
  expect([port(m, 0, 1).led, port(m, 0, 1).operational]).toEqual(["warning", "up"]);
  expect([port(m, 0, 2).led, port(m, 0, 2).operational]).toEqual(["warning", "unknown"]);   // todas fora: atenção, mas o estado da porta NÃO foi lido (não vira DOWN)
  expect(port(m, 0, 2).note).toContain("não foi lido");
  expect([port(m, 0, 5).led, port(m, 0, 5).operational]).toEqual(["unknown", "unknown"]);   // zero ONUs não prova nada
});

test("DOWN e DISABLED só vêm de leitura real da porta, independente das contagens de ONUs", () => {
  const states = { "0/0/0": { operational: "down" as const, administrative: "enabled" as const }, "0/0/1": { operational: "up" as const, administrative: "disabled" as const } };
  const m = buildPanel(fresh, [onu("0/0/0", "online"), onu("0/0/1", "online")], boards([[0, "H805GPFD"]]), { portStates: states });
  expect([port(m, 0, 0).led, port(m, 0, 1).led]).toEqual(["down", "disabled"]);
  expect(port(m, 0, 0).operationalSource).toBe("port_state");
});

test("dado velho ou parcial: desconhecido, contagem nula (nunca zero) e aviso", () => {
  const stale = buildPanel({ freshness: "stale" }, [onu("0/0/0", "online")], boards([[0, "H805GPFD"]]));
  expect([port(stale, 0, 0).led, port(stale, 0, 0).onus, port(stale, 0, 0).quality, stale.dataQuality]).toEqual(["unknown", { online: null, offline: null, total: null }, "stale", "stale"]);
  const oldOnu = buildPanel(fresh, [onu("0/0/0", "online", "stale")], boards([[0, "H805GPFD"]]));
  expect([port(oldOnu, 0, 0).led, port(oldOnu, 0, 0).quality]).toEqual(["unknown", "stale"]);
  const part = buildPanel(fresh, [onu("0/0/0", "online"), onu("0/0/0", "unknown")], boards([[0, "H805GPFD"]]));
  expect([port(part, 0, 0).quality, port(part, 0, 0).onus.total, port(part, 0, 0).led]).toEqual(["partial", null, "unknown"]);
  const cut = buildPanel(fresh, [onu("0/0/0", "online")], boards([[0, "H805GPFD"]]), { truncated: true });
  expect([cut.dataQuality, port(cut, 0, 0).quality, port(cut, 0, 0).led]).toEqual(["partial", "partial", "unknown"]);
});

test("inventário de placas desatualizado continua mostrando a placa, mas diz que está desatualizado", () => {
  const m = buildPanel(fresh, [], boards([[0, "H805GPFD"]], [], true));
  expect([m.boardsStale, m.slots[0]!.ports.length]).toEqual([true, 16]);
});
