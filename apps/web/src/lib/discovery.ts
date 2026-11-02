/** Fila de ONUs aguardando autorização (v2.5, FC25-01/02/03): tipos da API e rótulos. Somente leitura: nada aqui autoriza ONU nem escreve na OLT. */
export type Pending = {
  id: string; olt_id: string; olt_name: string; pon_path: string; serial: string; vendor_hint: string | null; source: string; authoritative: boolean;
  first_seen_at: string; last_seen_at: string; seen_count: number; condition: "new" | "waiting" | "stale" | "conflict"; reasons: string[];
  erp_association: string; customer: null; authorization: string;
};
export type PendingList = { items: Pending[]; total: number; offset: number; limit: number; truncated: boolean; scan_capped: boolean; fresh_window_minutes: number };

export const CONDITION_LABEL: Record<string, string> = { new: "Nova", waiting: "Aguardando", stale: "Dado antigo", conflict: "Conflito" };
export const CONDITION_MARK: Record<string, string> = { new: "●", waiting: "○", stale: "○", conflict: "▲" };
export const CONDITION_CLS: Record<string, string> = { new: "text-ok", waiting: "text-text", stale: "text-warn", conflict: "text-danger" };
export const REASON_LABEL: Record<string, string> = {
  already_registered: "Este serial já é uma ONU registrada neste provedor.", seen_elsewhere: "O mesmo serial apareceu em outra OLT/PON: uma das duas leituras está errada ou a ONU mudou de lugar.",
  not_seen_recently: "Não foi vista na última coleta: o dado é antigo (não significa que a ONU está desligada).",
};
export const SOURCE_LABEL: Record<string, string> = { edge_read: "Lida da OLT pelo Edge", manual_import: "Registrada à mão", fixture: "Fixture de teste" };
export const ASSOC_LABEL: Record<string, string> = { unavailable: "Indisponível: o ERP ainda não informa o serial das ONUs não registradas" };
export const FILTERS = ["new", "waiting", "stale", "conflict"] as const;

const PON = /^[0-9]{1,3}(\/[0-9]{1,3}){1,3}$/;
const SERIAL = /^[A-Za-z0-9]{4,32}$/;
/** "0/1/3 SERIAL [fabricante]" por linha → itens da API; qualquer linha fora do formato recusa o conjunto inteiro (`undefined`). */
export function parseLines(raw: string, observedAt: string): { pon_path: string; serial: string; vendor_hint?: string; observed_at: string }[] | undefined {
  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length === 0 || lines.length > 50) return undefined;
  const out: { pon_path: string; serial: string; vendor_hint?: string; observed_at: string }[] = [];
  for (const l of lines) {
    const [pon, serial, ...rest] = l.split(/\s+/);
    const vendor = rest.join(" ");
    if (!PON.test(pon ?? "") || !SERIAL.test(serial ?? "") || vendor.length > 40) return undefined;
    out.push({ pon_path: pon, serial, ...(vendor ? { vendor_hint: vendor } : {}), observed_at: observedAt });
  }
  return out;
}
