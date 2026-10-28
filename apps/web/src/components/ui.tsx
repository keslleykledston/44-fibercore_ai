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
  online: ["Online", "text-ok"], offline: ["Offline", "text-danger"], los: ["LOS", "text-danger"], dying_gasp: ["Falta de energia", "text-warn"],
  unknown: ["Desconhecido", "text-muted"], open: ["Aberto", "text-danger"], resolved: ["Resolvido", "text-ok"],
  healthy: ["Saudável", "text-ok"], degraded: ["Degradado", "text-warn"], unhealthy: ["Indisponível", "text-danger"],
  disabled: ["Desativado", "text-muted"], identified: ["Identificado", "text-muted"], observed: ["Observado", "text-text"], certified: ["Certificado", "text-ok"],
};
/** Texto + símbolo: a cor nunca é o único indicador (WCAG). */
export function StatusPill({ value }: { value: string }) {
  const [label, cls] = pill[value] ?? [value, "text-muted"];
  const dot = ["online", "healthy", "resolved", "certified"].includes(value) ? "●" : ["offline", "los", "unhealthy", "open"].includes(value) ? "▲" : "○";
  return <span className={`inline-flex items-center gap-1.5 text-sm ${cls}`}><span aria-hidden>{dot}</span>{label}</span>;
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
  return <div className="panel p-8 text-center" data-testid="empty-state"><p className="font-medium">{title}</p>{hint && <p className="mt-1 text-sm text-muted">{hint}</p>}</div>;
}
export function ErrorState({ title, hint }: { title: string; hint?: string }) {
  return <div role="alert" className="panel border-danger p-6" data-testid="error-state"><p className="font-medium text-danger">{title}</p>{hint && <p className="mt-1 text-sm text-muted">{hint}</p>}</div>;
}
export function Kpi({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return <div className="panel p-4"><div className="text-xs uppercase tracking-wide text-muted">{label}</div><div className="mt-1 text-3xl font-semibold" data-testid={`kpi-${label}`}>{value}</div>{hint && <div className="mt-1 text-xs text-muted">{hint}</div>}</div>;
}
