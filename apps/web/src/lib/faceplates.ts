/** Painéis frontais (faceplates) e matriz de PONs (ADR-0037; padrão visual do protótipo Lovable "FiberCore Command Center").
 *  Reproduções CONCEITUAIS e vetoriais: não são fotos nem fichas de fabricante, e o estado de cada LED é DERIVADO do que a OLT/ACS reportou, nunca lido do painel.
 *  Dado velho ou ausente produz "sem leitura" (anel tracejado), jamais "apagado"; só "sem energia" apaga tudo de fato. */
export type LedState = "on" | "off" | "blink" | "blink-fast" | "unknown";
export const LED_STATE_LABELS: Record<LedState, string> = { on: "Aceso", off: "Apagado", blink: "Piscando", "blink-fast": "Piscando rápido", unknown: "Sem leitura" };
export type LedRole = "power" | "optical-sync" | "optical-fault" | "lan" | "wireless" | "pairing";
export type PortKind = "power" | "sc" | "rj45" | "rj11" | "usb" | "button" | "pinhole";
export type FaceplateLed = { id: string; label: string; role: LedRole; meaning: string };
export type FaceplatePort = { id: string; label: string; kind: PortKind };
export type DeviceFaceplate = { model: string; vendor: string; form: string; leds: FaceplateLed[]; ports: FaceplatePort[]; source: string };

const led = (id: string, label: string, role: LedRole, meaning: string): FaceplateLed => ({ id, label, role, meaning });
const port = (id: string, label: string, kind: PortKind): FaceplatePort => ({ id, label, kind });
const LAN = (n: number) => `Link ativo na porta LAN${n}`;
const COMMON = [
  led("power", "Power", "power", "Energia elétrica no equipamento"),
  led("los", "LOS", "optical-fault", "Perda de sinal óptico: indício de fibra/LOS"),
  led("pon", "PON", "optical-sync", "Sincronismo estabelecido com a OLT"),
];
const CONCEPTUAL = "Reprodução vetorial conceitual: não é imagem do fabricante";

const EG8145V5: DeviceFaceplate = {
  model: "EG8145V5", vendor: "Huawei EchoLife", form: "Caixa horizontal com antenas traseiras",
  leds: [...COMMON, led("lan1", "LAN1", "lan", LAN(1)), led("lan2", "LAN2", "lan", LAN(2)), led("lan3", "LAN3", "lan", LAN(3)), led("lan4", "LAN4", "lan", LAN(4)),
    led("wifi", "Wi-Fi", "wireless", "Interface sem fio ativa"), led("wps", "WPS", "pairing", "Emparelhamento em curso")],
  ports: [port("pwr", "5V", "power"), port("pon", "PON", "sc"), port("lan1", "LAN1", "rj45"), port("lan2", "LAN2", "rj45"), port("lan3", "LAN3", "rj45"), port("lan4", "LAN4", "rj45"),
    port("tel1", "TEL1", "rj11"), port("tel2", "TEL2", "rj11"), port("usb", "USB", "usb"), port("wps", "WPS", "button"), port("rst", "Reset", "pinhole")],
  source: CONCEPTUAL,
};
const HG8010H: DeviceFaceplate = {
  model: "HG8010H", vendor: "Huawei EchoLife", form: "Caixa pequena, sem Wi-Fi",
  leds: [...COMMON, led("lan1", "LAN1", "lan", LAN(1))],
  ports: [port("pwr", "5V", "power"), port("pon", "PON", "sc"), port("lan1", "LAN1", "rj45"), port("rst", "Reset", "pinhole")],
  source: CONCEPTUAL,
};
const GENERIC: DeviceFaceplate = {
  model: "Painel genérico", vendor: "Modelo sem painel catalogado", form: "Representação neutra com os LEDs essenciais",
  leds: [...COMMON, led("lan1", "LAN1", "lan", LAN(1)), led("wifi", "Wi-Fi", "wireless", "Interface sem fio ativa")],
  ports: [port("pwr", "5V", "power"), port("pon", "PON", "sc"), port("lan1", "LAN1", "rj45"), port("lan2", "LAN2", "rj45"), port("wps", "WPS", "button")],
  source: "Painel genérico usado quando o modelo não está na biblioteca",
};
export const FACEPLATES: DeviceFaceplate[] = [EG8145V5, HG8010H, GENERIC];

/** Resolve o painel de um modelo; nunca falha: cai no genérico (e o texto diz que é genérico). */
export function faceplateFor(model: string | null | undefined): DeviceFaceplate {
  const key = (model ?? "").trim().toLowerCase();
  return FACEPLATES.find((f) => f !== GENERIC && key.includes(f.model.toLowerCase())) ?? GENERIC;
}

/** O que a OLT reportou sobre a ONU (status + frescor). */
export type Reported = { status: string; freshness: string };
const usable = (r: Reported) => r.freshness === "fresh" && r.status !== "unknown";

export type LedReading = { leds: Record<string, LedState>; summary: string; lastKnown: boolean };
export function readLeds(fp: DeviceFaceplate, r: Reported): LedReading {
  const lastKnown = !usable(r);
  /** Só vira "aceso/apagado" o que o estado reportado da ONU realmente implica; tudo o mais fica "sem leitura" (a OLT não lê LAN, Wi-Fi nem WPS do aparelho):
   *  online = registrada e sincronizada na PON (logo energizada); los = sem sincronismo com falha de sinal (a energia é desconhecida: pode ser fibra OU aparelho desligado);
   *  dying_gasp = falta de energia reportada pelo próprio aparelho; offline sem causa = só o sincronismo é conhecido. */
  const stateOf = (l: FaceplateLed): LedState => {
    if (lastKnown) return "unknown";
    if (r.status === "dying_gasp") return "off";
    switch (l.role) {
      case "power": return r.status === "online" ? "on" : "unknown";
      case "optical-sync": return r.status === "online" ? "on" : "off";
      case "optical-fault": return r.status === "los" ? "blink-fast" : r.status === "online" ? "off" : "unknown";
      default: return "unknown";   // lan, wireless, pairing: sem telemetria específica
    }
  };
  const summary = lastKnown ? (r.status === "unknown" ? "O painel não pode ser preenchido agora: não há coleta ativa." : "O painel não pode ser preenchido agora: o dado está defasado.")
    : r.status === "online" ? "Energia e sincronismo presentes (registrada na PON). LAN e Wi-Fi não são lidos pela OLT."
    : r.status === "los" ? "Sem sincronismo óptico, com perda de sinal (LOS) reportada: indício de fibra/LOS. A energia do equipamento não é conhecida."
    : r.status === "dying_gasp" ? "Falta de energia reportada pelo próprio equipamento (dying gasp): nenhum LED deve estar aceso."
    : "Sem sincronismo óptico; a causa não foi determinada.";
  return { leds: Object.fromEntries(fp.leds.map((l) => [l.id, stateOf(l)])) as Record<string, LedState>, summary, lastKnown };
}

export function miniLeds(fp: DeviceFaceplate): FaceplateLed[] {
  const keep: LedRole[] = ["power", "optical-sync", "optical-fault", "lan", "wireless"];
  return fp.leds.filter((l) => keep.includes(l.role)).slice(0, 4);
}

/* ---------- Matriz de PONs (painel frontal da OLT) ---------- */
export type PonState = "ok" | "fora" | "energia" | "los" | "sem-leitura";
export const PON_STATE_LABEL: Record<PonState, string> = { ok: "Sem ONUs fora", fora: "ONUs fora do ar", energia: "Queda de energia", los: "Perda de sinal óptico (LOS)", "sem-leitura": "Sem leitura" };
export type PonSummary = { path: string; total: number; down: number; state: PonState };
const DOWN = new Set(["offline", "los", "dying_gasp"]);

/** Prioridade do que a célula pode afirmar: LOS > energia > fora > ok > sem leitura. PON só com dado velho ou sem coleta é "sem leitura", nunca "fora". */
export function summarizePons(onus: { pon_path: string | null; status: string; freshness: string }[]): PonSummary[] {
  const by = new Map<string, typeof onus>();
  for (const o of onus) { const k = o.pon_path ?? "—"; by.set(k, [...(by.get(k) ?? []), o]); }
  const out: PonSummary[] = [];
  for (const [path, list] of by) {
    const fresh = list.filter((o) => o.freshness === "fresh" && o.status !== "unknown");
    const down = fresh.filter((o) => DOWN.has(o.status));
    const state: PonState = fresh.length === 0 ? "sem-leitura" : fresh.some((o) => o.status === "los") ? "los" : fresh.some((o) => o.status === "dying_gasp") ? "energia" : down.length ? "fora" : "ok";
    out.push({ path, total: list.length, down: down.length, state });
  }
  return out.sort((a, b) => a.path.localeCompare(b.path, "pt-BR", { numeric: true }));
}
