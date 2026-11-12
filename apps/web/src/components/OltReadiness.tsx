import { readinessSteps, stageText, type Readiness } from "@/lib/oltConnection";

const mark = { done: "✓", current: "●", pending: "○" } as const;
const cls = { done: "text-ok", current: "font-semibold text-accent", pending: "text-muted" } as const;

/**
 * Prontidão da OLT (ADR-0046 D3): Cadastrada → Conexão aplicada → Confirmação no Edge → Credencial aplicada → Testada. O estado atual vem da API (`readiness.stage`); aqui só se mostra.
 * Telnet e o cadastro simples não têm cadeia: uma frase. O estado nunca é só cor: cada item leva um símbolo e o atual leva `aria-current`.
 */
export function OltReadiness({ r, testId = "frota-prontidao" }: { r: Readiness; testId?: string }) {
  const steps = readinessSteps(r);
  if (!steps) return <p className="text-xs text-muted" data-testid={testId} data-stage={r.stage}><span className="sr-only">Prontidão: </span>{stageText(r)}</p>;
  return (
    <div data-testid={testId} data-stage={r.stage}>
      <p className="sr-only">Prontidão: {stageText(r)}</p>
      <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs" aria-label="Prontidão da OLT">
        {steps.map((s, i) => (
          <li key={s.key} className={`inline-flex items-center gap-1 ${cls[s.state]}`} aria-current={s.state === "current" ? "step" : undefined} data-state={s.state}>
            {i > 0 && <span aria-hidden className="text-muted">→</span>}<span aria-hidden>{mark[s.state]}</span>{s.label}
          </li>))}
      </ol>
    </div>
  );
}
