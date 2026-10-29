import type { ReactNode } from "react";

export function Card({ title, children, testid }: { title: string; children: ReactNode; testid: string }) {
  return <section aria-label={title} data-testid={testid} className="panel p-4"><h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">{title}</h2>{children}</section>;
}
export function Row({ k, children }: { k: string; children: ReactNode }) {
  return <div className="flex flex-wrap items-baseline justify-between gap-2 py-1 text-sm"><dt className="text-muted">{k}</dt><dd className="text-right">{children}</dd></div>;
}
