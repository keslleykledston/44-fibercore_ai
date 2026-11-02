import type { Olt, Onu } from "@/lib/types";

/** Painel frontal da Huawei MA5608T (pacote FiberCore-MA5608T v1.0, adaptado): as PONs de cada cartão de serviço, com o LED de cada uma.
 *  Regras de honestidade (o painel é uma VISTA dos dados, nunca uma fonte):
 *  - cartão presente/vazio/desconhecido vem da leitura do inventário (`olt.board`); ausência de leitura é DESCONHECIDO, nunca "vazio";
 *  - a capacidade de PONs vem do MODELO da placa (GPFD = 16, GPBD/GPBH = 8); modelo que não conhecemos NÃO ganha 16 portas;
 *  - o estado da PORTA (laser) não se confunde com o das ONUs: sem leitura da porta, só "UP" é provado (há ONU online nela); "DOWN" nunca é deduzido de ONUs;
 *  - contagem de ONU só aparece como fresca se o dado é fresco; dado velho vira DESCONHECIDO com aviso. */
export type Led = "up" | "down" | "warning" | "disabled" | "unknown";
export type Presence = "present" | "empty" | "unknown";
export type Quality = "fresh" | "stale" | "partial" | "unavailable";
export type BoardRead = { slot: number; name: string; status: string };
export type BoardsResult = { boards: BoardRead[]; empty_slots: number[]; observedAt: string | null; stale: boolean; demo?: boolean };
export type PortState = { operational: "up" | "down" | "unknown"; administrative: "enabled" | "disabled" | "unknown" };

export type PortModel = {
  key: string; slot: number; port: number; led: Led;
  operational: "up" | "down" | "unknown"; operationalSource: "port_state" | "onu_online" | "none";
  administrative: "enabled" | "disabled" | "unknown";
  onus: { online: number | null; offline: number | null; total: number | null };
  quality: Quality; note: string;
};
export type SlotModel = {
  slot: number; presence: Presence; evidence: "board_read" | "onu_data" | "none"; boardModel: string | null; boardStatus: string | null;
  ponCapacity: number | null; supported: boolean; ports: PortModel[];
};
export type OltPanelModel = { slots: SlotModel[]; boardsObservedAt: string | null; boardsStale: boolean; boardsDemo: boolean; truncated: boolean; dataQuality: Quality };

export const SERVICE_SLOTS = [0, 1] as const;
const DOWN = new Set(["offline", "los", "dying_gasp"]);

/** Capacidade de PONs por MODELO de placa GPON da família MA56xx. Desconhecido => null (o painel diz "cartão sem template", não inventa portas). */
export function ponCapacityOf(model: string | null): number | null {
  if (!model) return null;
  const m = model.toUpperCase();
  if (/GPFD$/.test(m)) return 16;   // observado na OLT do laboratório: H805GPFD com PON 0..15 em cada cartão
  if (/GP(BD|BH)$/.test(m)) return 8;
  return null;
}
export const isMa5608t = (o: Pick<Olt, "vendor" | "model"> | null | undefined) => !!o && o.vendor.toLowerCase() === "huawei" && (o.model ?? "").toUpperCase() === "MA5608T";
export const portKey = (frame: number, slot: number, port: number) => `${frame}/${slot}/${port}`;

const LED_TEXT: Record<Led, string> = { up: "UP", down: "DOWN", warning: "ATENÇÃO", disabled: "DESABILITADA", unknown: "SEM LEITURA" };
export const ledLabel = (l: Led) => LED_TEXT[l];

function buildPort(frame: number, slot: number, port: number, rows: Onu[], ctx: { oltFresh: boolean; truncated: boolean; state?: PortState }): PortModel {
  const key = portKey(frame, slot, port);
  const fresh = rows.filter((o) => o.freshness === "fresh" && o.status !== "unknown");
  const unreadable = rows.length - fresh.length;   // ONUs desta porta sem dado fresco ou com estado desconhecido
  const online = fresh.filter((o) => o.status === "online").length;
  const offline = fresh.filter((o) => DOWN.has(o.status)).length;
  const quality: Quality = !ctx.oltFresh || (rows.length > 0 && fresh.length === 0) ? "stale" : ctx.truncated || unreadable > 0 ? "partial" : "fresh";
  const known = quality === "fresh";
  const onus = quality === "stale" ? { online: null, offline: null, total: null } : { online, offline, total: known ? online + offline : null };
  const administrative = ctx.state?.administrative ?? "unknown";
  let operational: PortModel["operational"] = ctx.state?.operational ?? "unknown";
  let operationalSource: PortModel["operationalSource"] = ctx.state ? "port_state" : "none";
  if (operational === "unknown" && quality !== "stale" && online > 0) { operational = "up"; operationalSource = "onu_online"; }   // uma ONU online PROVA a porta operacional; zero ONU não prova nada
  let led: Led = "unknown", note = "";
  if (quality === "stale") note = "Sem leitura recente das ONUs desta porta: nada é afirmado.";
  else if (administrative === "disabled") led = "disabled";
  else if (operational === "down") led = "down";
  else if (operational === "up") led = offline > 0 ? "warning" : unreadable > 0 || ctx.truncated ? "unknown" : "up";
  else if (online === 0 && offline > 0) { led = "warning"; note = "Todas as ONUs lidas estão fora; o estado da porta não foi lido (pode ser a PON)."; }
  else note = rows.length === 0 ? "Sem ONUs provisionadas lidas; o estado da porta não foi lido." : "O estado da porta não foi lido.";
  if (quality === "partial") note = [note, "Leitura parcial: há ONUs sem dado fresco ou acima do limite de leitura."].filter(Boolean).join(" ");
  if (operationalSource === "onu_online") note = [note, "Porta UP provada por ONU online (a porta em si não foi lida)."].filter(Boolean).join(" ");
  return { key, slot, port, led, operational, operationalSource, administrative, onus, quality, note };
}

export function buildPanel(olt: Pick<Olt, "freshness">, onus: Onu[], boards: BoardsResult | null, opts: { truncated?: boolean; portStates?: Record<string, PortState> } = {}): OltPanelModel {
  const byPort = new Map<string, Onu[]>();
  for (const o of onus) if (o.pon_path) byPort.set(o.pon_path, [...(byPort.get(o.pon_path) ?? []), o]);
  const oltFresh = olt.freshness === "fresh";
  const truncated = !!opts.truncated;
  const slots: SlotModel[] = SERVICE_SLOTS.map((slot) => {
    const read = boards?.boards.find((b) => b.slot === slot) ?? null;
    const emptyRead = boards?.empty_slots.includes(slot) ?? false;
    const seen = [...byPort.keys()].some((k) => k.startsWith(`0/${slot}/`));   // ONUs coletadas nesta placa são evidência POSITIVA de que ela existe
    const presence: Presence = read ? "present" : emptyRead ? "empty" : seen ? "present" : "unknown";
    const evidence: SlotModel["evidence"] = read || emptyRead ? "board_read" : seen ? "onu_data" : "none";
    const cap = ponCapacityOf(read?.name ?? null);
    const supported = presence === "present" && cap !== null;
    const ports = supported ? Array.from({ length: cap }, (_, p) => buildPort(0, slot, p, byPort.get(portKey(0, slot, p)) ?? [], { oltFresh, truncated, ...(opts.portStates?.[portKey(0, slot, p)] ? { state: opts.portStates[portKey(0, slot, p)]! } : {}) })) : [];
    return { slot, presence, evidence, boardModel: read?.name ?? null, boardStatus: read?.status ?? null, ponCapacity: cap, supported, ports };
  });
  const dataQuality: Quality = !oltFresh ? "stale" : truncated ? "partial" : "fresh";
  return { slots, boardsObservedAt: boards?.observedAt ?? null, boardsStale: boards?.stale ?? false, boardsDemo: boards?.demo ?? false, truncated, dataQuality };
}

/** Texto curto para quem não vê a cor (aria-label, legenda e popover). */
export function describePort(p: PortModel): string {
  const c = p.onus;
  const n = (v: number | null) => (v === null ? "—" : String(v));
  return `PON ${p.key}: ${ledLabel(p.led)} · ONUs UP ${n(c.online)}, DOWN ${n(c.offline)}`;
}
