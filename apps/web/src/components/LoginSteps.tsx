/** Indicador das etapas do acesso: credenciais → verificação (só com MFA) → workspace (só com mais de um). Texto + número: a cor não é o único sinal. */
export function LoginSteps({ current }: { current: "credenciais" | "verificacao" | "workspace" }) {
  const steps = [
    { id: "credenciais", label: "Credenciais" },
    { id: "verificacao", label: "Verificação" },
    { id: "workspace", label: "Workspace" },
  ] as const;
  const at = steps.findIndex((s) => s.id === current);
  return (
    <ol aria-label="Etapas do acesso" data-testid="login-steps" className="flex items-center justify-center gap-2 text-xs text-muted">
      {steps.map((s, i) => (
        <li key={s.id} aria-current={i === at ? "step" : undefined} className={`flex items-center gap-1.5 ${i === at ? "font-semibold text-text" : ""}`}>
          <span aria-hidden className={`grid h-5 w-5 place-items-center rounded-full border text-[11px] ${i === at ? "border-accent bg-accent-soft text-text" : i < at ? "border-ok text-ok" : "border-line"}`}>{i < at ? "✓" : i + 1}</span>
          {s.label}{i === at && <span className="sr-only"> (etapa atual)</span>}
          {i < steps.length - 1 && <span aria-hidden className="mx-1 text-line">—</span>}
        </li>
      ))}
    </ol>
  );
}
