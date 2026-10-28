import Link from "next/link";
import type { ReactNode } from "react";

export function DataFreshness({ freshness, observedAt }: { freshness?: string | null; observedAt?: string | null }) {
  const label = freshness === "fresh" ? "Atualizado" : freshness === "stale" ? "Dados defasados" : "Sem coleta";
  const ago = observedAt ? ` · ${ago_(observedAt)}` : "";
  return <span data-testid="freshness" className={`text-xs ${freshness === "stale" ? "text-warn" : "text-muted"}`}>{label}{ago}</span>;
}
function ago_(iso: string) {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 90) return "agora há pouco";
  if (s < 5400) return `há ${Math.round(s / 60)} min`;
  if (s < 172800) return `há ${Math.round(s / 3600)} h`;
  return `há ${Math.round(s / 86400)} d`;
}

const pill: Record<string, [string, string]> = {
  online: ["Online", "bg-ok-soft text-ok"], offline: ["Offline", "bg-danger-soft text-danger"], los: ["LOS", "bg-danger-soft text-danger"], dying_gasp: ["Falta de energia", "bg-warn-soft text-warn"],
  unknown: ["Desconhecido", "bg-stale-soft text-muted"], open: ["Aberto", "bg-danger-soft text-danger"], resolved: ["Resolvido", "bg-ok-soft text-ok"],
  healthy: ["Saudável", "bg-ok-soft text-ok"], degraded: ["Degradado", "bg-warn-soft text-warn"], unhealthy: ["Indisponível", "bg-danger-soft text-danger"],
  disabled: ["Desativado", "bg-stale-soft text-muted"], identified: ["Identificado", "bg-stale-soft text-muted"], observed: ["Observado", "bg-accent-soft text-text"], certified: ["Certificado", "bg-ok-soft text-ok"],
};
/** Texto + símbolo: a cor nunca é o único indicador (WCAG). */
export function StatusPill({ value }: { value: string }) {
  const [label, cls] = pill[value] ?? [value, "bg-stale-soft text-muted"];
  const dot = ["online", "healthy", "resolved", "certified"].includes(value) ? "●" : ["offline", "los", "unhealthy", "open"].includes(value) ? "▲" : "○";
  return <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${cls}`}><span aria-hidden>{dot}</span>{label}</span>;
}

export function PageHeader({ title, subtitle, helpSlug, children }: { title: string; subtitle?: string; helpSlug: string; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-3">{children}<HelpContextLink slug={helpSlug} /></div>
    </div>
  );
}

export function HelpContextLink({ slug }: { slug: string }) {
  return <Link href={`/ajuda/${slug}`} data-testid="help-link" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent underline-offset-4 hover:underline">Ajuda desta tela</Link>;
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return <div className="panel px-6 py-12 text-center" data-testid="empty-state"><p className="font-medium">{title}</p>{hint && <p className="mt-1 text-sm text-muted">{hint}</p>}</div>;
}
export function ErrorState({ title, hint }: { title: string; hint?: string }) {
  return <div role="alert" className="panel border-danger p-6" data-testid="error-state"><p className="font-medium text-danger">{title}</p>{hint && <p className="mt-1 text-sm text-muted">{hint}</p>}</div>;
}
export function Kpi({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return <div className="panel p-4"><div className="text-xs text-muted">{label}</div><div className="tabular mt-1 text-3xl font-semibold" data-testid={`kpi-${label}`}>{value}</div>{hint && <div className="mt-1 text-xs text-muted">{hint}</div>}</div>;
}
