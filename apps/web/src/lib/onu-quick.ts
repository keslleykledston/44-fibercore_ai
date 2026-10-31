/** Resumo rápido da ONU (UX 2.2, Quick Inspector). Compõe, NO SERVIDOR, o que as rotas existentes já devolvem (ONU 360 + assinante da ONU): nenhuma rota nova na API.
 *  Regras de negócio da matriz de estados: a PON (OLT) e o ACS são fontes SEPARADAS; ACS sem contato não é ONU offline; RX nulo não é 0 dBm; sem limiar homologado a potência
 *  fica neutra; associação fraca não é cliente confirmado; sem dado nunca vira verde. */
import type { Onu360, OnuCustomer } from "@/lib/types";

export type Tone = "ok" | "warn" | "bad" | "neutral";
export type QuickModel = {
  onu: { id: string; serial: string; olt_name: string; olt_vendor_model: string; pon_ref: string | null };
  pon: { label: string; detail: string | null; tone: Tone; fresh: boolean; observed_at: string | null; source: "olt" };
  acs: { label: string; tone: Tone; observed_at: string | null; source: "acs" | null; vendor_model: string | null };
  optical: { rx_dbm: number | null; label: string; observed_at: string | null; source: "olt"; severity: "unknown" };
  association: { state: "confirmed" | "low" | "unassociated" | "restricted" | "error"; label: string; customer: string | null };
  can_open_360: true;
};

const OFFLINE: Record<string, string> = { offline: "PON offline", los: "PON offline · sem sinal (LOS)", dying_gasp: "PON offline · falta de energia" };

export function buildQuick(o: Onu360, customer: { status: number; data: OnuCustomer | null }): QuickModel {
  const fresh = o.freshness === "fresh";
  let pon: QuickModel["pon"];
  if (o.status === "unknown" || !o.observed_at) pon = { label: "Estado PON desconhecido", detail: null, tone: "neutral", fresh: false, observed_at: o.observed_at, source: "olt" };
  else if (!fresh) pon = { label: "PON: dados defasados", detail: "Última observação, não o estado atual.", tone: "neutral", fresh: false, observed_at: o.observed_at, source: "olt" };
  else if (o.status === "online") pon = { label: "PON registrada", detail: null, tone: "ok", fresh: true, observed_at: o.observed_at, source: "olt" };
  else pon = { label: OFFLINE[o.status] ?? "Estado PON desconhecido", detail: null, tone: OFFLINE[o.status] ? "bad" : "neutral", fresh: true, observed_at: o.observed_at, source: "olt" };

  const cpe = o.cpe;
  let acs: QuickModel["acs"];
  if (!cpe || cpe.link === "unavailable") acs = { label: "ACS: sem informação para esta ONU", tone: "neutral", observed_at: null, source: null, vendor_model: null };
  else if (cpe.link !== "confirmed" || !cpe.device) acs = { label: "Sem roteador vinculado", tone: "neutral", observed_at: null, source: null, vendor_model: null };
  else {
    const q = cpe.provenance?.quality;
    const vm = [cpe.device.vendor, cpe.device.model].filter(Boolean).join(" ") || null;
    acs = q === "fresh" ? { label: "ACS comunicando", tone: "ok", observed_at: cpe.provenance?.observed_at ?? null, source: "acs", vendor_model: vm }
      : q === "stale" ? { label: "ACS sem contato recente", tone: "warn", observed_at: cpe.provenance?.observed_at ?? null, source: "acs", vendor_model: vm }
      : { label: "Estado ACS desconhecido", tone: "neutral", observed_at: null, source: "acs", vendor_model: vm };
  }

  let association: QuickModel["association"];
  if (customer.status === 403) association = { state: "restricted", label: "Dados do cliente restritos", customer: null };
  else if (customer.status !== 200 || !customer.data) association = { state: "error", label: "Não foi possível carregar o cliente", customer: null };
  else if (customer.data.association === "approved") association = { state: "confirmed", label: "Cliente associado", customer: customer.data.display_name ?? null };
  else if (customer.data.association === "suggested") association = { state: "low", label: "Vínculo de cliente sem confirmação", customer: null };
  else association = { state: "unassociated", label: "Cliente não associado", customer: null };

  return {
    onu: { id: o.id, serial: o.serial, olt_name: o.olt.name, olt_vendor_model: [o.olt.vendor, o.olt.model].filter(Boolean).join(" "), pon_ref: o.pon?.path ?? null },
    pon, acs,
    optical: { rx_dbm: o.rx_dbm, label: o.rx_dbm === null ? "RX não disponível" : `RX ${o.rx_dbm.toLocaleString("pt-BR")} dBm`, observed_at: o.rx_dbm === null ? null : o.observed_at, source: "olt", severity: "unknown" },
    association, can_open_360: true,
  };
}

const NAME = /^[^\x00-\x1f\x7f]{0,200}$/;
/** O que a tela aceita do BFF: formato fechado, texto sem controle, tons conhecidos. */
export function readQuick(d: unknown): QuickModel | null {
  const m = d as QuickModel | null;
  const tones = ["ok", "warn", "bad", "neutral"];
  if (!m || typeof m !== "object" || !m.onu || !m.pon || !m.acs || !m.optical || !m.association) return null;
  const strs = [m.onu.id, m.onu.serial, m.onu.olt_name, m.pon.label, m.acs.label, m.optical.label, m.association.label];
  if (!strs.every((s) => typeof s === "string" && NAME.test(s))) return null;
  if (!tones.includes(m.pon.tone) || !tones.includes(m.acs.tone)) return null;
  if (m.optical.rx_dbm !== null && typeof m.optical.rx_dbm !== "number") return null;
  if (!["confirmed", "low", "unassociated", "restricted", "error"].includes(m.association.state)) return null;
  if (m.association.customer !== null && !(typeof m.association.customer === "string" && NAME.test(m.association.customer))) return null;
  return m;
}
