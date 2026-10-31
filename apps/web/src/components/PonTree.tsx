import Link from "next/link";
import { ponHref } from "@/components/PonMatrix";
import type { PonSummary } from "@/lib/faceplates";
import type { Olt } from "@/lib/types";

/** Árvore OLT › PON (ADR-0037): navegação por links (a seleção vive na URL: recarregar ou compartilhar a tela mantém o recorte). */
export function PonTree({ olts, oltId, ponId, pons }: { olts: Olt[]; oltId: string; ponId?: string; pons: PonSummary[] }) {
  return (
    <nav aria-label="Árvore de OLTs e PONs" className="panel p-2" data-testid="pon-tree">
      <ul className="flex flex-col">
        {olts.map((o) => (
          <li key={o.id}>
            <Link href={ponHref(o.id)} aria-current={o.id === oltId && !ponId ? "page" : undefined}
              className={`flex min-h-touch items-center gap-2 rounded-btn px-2 text-sm hover:bg-surface-2 ${o.id === oltId && !ponId ? "bg-accent-soft" : ""}`}>
              <span aria-hidden className={`text-xs text-muted ${o.id === oltId ? "rotate-90" : ""}`}>▸</span>
              <span className="flex-1 break-words font-medium">{o.name}</span>
              <span className="tabular text-xs text-muted">{o.onu_count}</span>
            </Link>
            {o.id === oltId && pons.length > 0 && (
              <ul className="ml-5 flex flex-col pb-1">
                {pons.map((p) => (
                  <li key={p.path}>
                    <Link href={ponHref(o.id, p.path)} aria-current={p.path === ponId ? "page" : undefined}
                      className={`flex min-h-10 items-center gap-2 rounded-btn px-2 text-sm hover:bg-surface-2 ${p.path === ponId ? "bg-accent-soft font-medium" : ""}`}>
                      <span className="flex-1">PON {p.path}</span>
                      <span className="tabular text-xs text-muted">{p.total}</span>
                      {p.down > 0 && <span className={`tabular text-xs ${p.state === "los" ? "text-danger" : "text-warn"}`}>{p.down} fora{p.state === "los" ? " · LOS" : p.state === "energia" ? " · energia" : ""}</span>}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
