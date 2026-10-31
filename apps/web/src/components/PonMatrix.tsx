import Link from "next/link";
import { causesText, PON_STATE_LABEL, type PonState, type PonSummary } from "@/lib/faceplates";

const RING: Record<PonState, string> = {
  ok: "border-ok bg-ok-soft", fora: "border-warn bg-warn-soft", los: "border-danger bg-danger-soft", energia: "border-warn border-dashed bg-warn-soft", "sem-leitura": "border-line bg-stale-soft fp-hatch",
};
const DOT: Record<PonState, string> = { ok: "bg-ok", fora: "bg-warn", los: "bg-danger fp-blink", energia: "bg-warn rounded-none", "sem-leitura": "bg-muted" };
/** Texto curto visível da célula (a cor não é o único indicador) e o rótulo completo do estado, só para leitor de tela. */
const short = (p: PonSummary) => {
  const causes = causesText(p);
  return p.state === "sem-leitura" ? `${p.total} ONU${p.total === 1 ? "" : "s"} · sem leitura` : p.down ? `${p.total} · ${p.down} fora${causes ? ` · ${causes}` : ""}` : `${p.total} ONU${p.total === 1 ? "" : "s"}`;
};
const full = (p: PonSummary) => `${PON_STATE_LABEL[p.state]} · ${p.total} ONU${p.total === 1 ? "" : "s"}${p.down ? `, ${p.down} fora${causesText(p) ? ` (${causesText(p)})` : ""}` : ""}`;
export const ponHref = (olt: string, pon?: string) => `/rede?olt=${encodeURIComponent(olt)}${pon ? `&pon=${encodeURIComponent(pon)}` : ""}`;

/** Painel frontal da OLT (ADR-0037, padrão Lovable). Âmbar = há ONUs fora do ar (numa rede real quase toda PON tem alguma: vermelho em toda célula não informaria nada); vermelho só para LOS observado.
 * uma célula por PON com o resumo em TEXTO, derivado do estado das ONUs carregadas; cada célula leva àquela PON.
 *  PON só com dado velho é "sem leitura", nunca "fora"; a cor nunca é o único indicador. */
export function PonMatrix({ oltId, oltName, model, pons, activePon, truncated }: { oltId: string; oltName: string; model: string | null; pons: PonSummary[]; activePon?: string; truncated: boolean }) {
  return (
    <section aria-label={`Painel frontal da OLT ${oltName}`} className="panel mb-4 p-4" data-testid="pon-matrix">
      <div className="mb-3">
        <h2 className="text-sm font-semibold">Painel frontal · {model ?? oltName}</h2>
        <p className="mt-0.5 text-xs text-muted">Matriz de PONs · estado derivado das ONUs coletadas{truncated ? " (lista parcial: há mais ONUs do que o limite de leitura)" : ""}</p>
      </div>
      {pons.length === 0 ? <p className="text-sm text-muted">Nenhuma PON conhecida nesta OLT ainda.</p> : (
        <ul className="flex flex-wrap gap-1.5">
          {pons.map((p) => (
            <li key={p.path}>
              <Link href={ponHref(oltId, p.path)} aria-current={p.path === activePon ? "true" : undefined} data-testid="pon-cell" data-state={p.state}
                title={full(p)} className={`flex min-h-touch min-w-[92px] flex-col items-center gap-0.5 rounded-btn border px-2.5 py-1.5 ${RING[p.state]} ${p.path === activePon ? "outline outline-2 outline-offset-2 outline-[color:var(--accent)]" : ""}`}>
                <span className="flex items-center gap-1.5"><span className={`size-2 rounded-full ${DOT[p.state]}`} aria-hidden /><span className="tabular text-xs font-medium">{p.path}</span></span>
                <span className="text-xs leading-tight text-muted" aria-hidden>{short(p)}</span><span className="sr-only">{full(p)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 border-t border-line pt-2 text-xs text-muted">Reprodução conceitual: cada célula resume o que as ONUs daquela PON reportaram. Dado defasado vira “sem leitura”, não “fora”.</p>
    </section>
  );
}
