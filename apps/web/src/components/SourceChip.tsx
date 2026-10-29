import type { Provenance } from "@/lib/types";

const SOURCE: Record<string, string> = { olt_snapshot: "Leitura da OLT pelo Edge (somente leitura)", genieacs_nbi: "GenieACS (NBI) pelo Edge", erp_csv: "ERP (importação CSV)" };
const QUALITY: Record<string, string> = { fresh: "Atualizado", stale: "Dados defasados", unknown: "Sem coleta", conflict: "Fontes divergentes" };

const label = (source: string) => SOURCE[source] ?? (source.startsWith("erp:") ? `ERP (${source.slice(4)})` : source);

function ago(iso: string) {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 90) return "agora há pouco";
  if (s < 5400) return `há ${Math.round(s / 60)} min`;
  if (s < 172800) return `há ${Math.round(s / 3600)} h`;
  return `há ${Math.round(s / 86400)} d`;
}

/** De onde veio o dado, de quando é e quão fresco está AGORA. Defasado nunca é lido como "offline": é a idade do dado. */
export function SourceChip({ p }: { p: Provenance }) {
  const warn = p.quality !== "fresh";
  return (
    <span data-testid="source-chip" className="inline-flex flex-wrap items-center justify-end gap-x-2 text-xs text-muted">
      <span>{label(p.source)}</span>
      <span aria-hidden>·</span>
      <span data-testid="freshness" className={warn ? "text-warn" : undefined}>{QUALITY[p.quality] ?? p.quality}{p.observed_at ? ` · ${ago(p.observed_at)}` : ""}</span>
    </span>
  );
}
