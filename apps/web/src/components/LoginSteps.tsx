/**
 * Etapas do acesso já percorridas + a atual. As seguintes NÃO aparecem: verificação só existe para quem tem MFA e o workspace só
 * quando há mais de um, e antes de autenticar não dá para saber (nem revelar) qual é o caso. Texto + número: a cor não é o único sinal.
 */
export function LoginSteps({ current }: { current: "credenciais" | "verificacao" | "workspace" }) {
  const label = { credenciais: "Credenciais", verificacao: "Verificação", workspace: "Workspace" } as const;
  // Só o que é certo: credenciais já feitas (se não estamos nelas) e a etapa atual. "Verificação" nunca é afirmada como concluída
  // no workspace, porque quem não usa MFA não passou por ela.
  const shown = current === "credenciais" ? [current] : (["credenciais", current] as const);
  return (
    <ol aria-label="Etapas do acesso" data-testid="login-steps" className="flex items-center justify-center gap-2 text-xs text-muted">
      {shown.map((id, i) => {
        const now = id === current;
        return (
          <li key={id} aria-current={now ? "step" : undefined} className={`flex items-center gap-1.5 ${now ? "font-semibold text-text" : ""}`}>
            <span aria-hidden className={`grid h-5 w-5 place-items-center rounded-full border text-[11px] ${now ? "border-accent bg-accent-soft text-text" : "border-ok text-ok"}`}>{now ? i + 1 : "✓"}</span>
            {label[id]}{now ? <span className="sr-only"> (etapa atual)</span> : <span className="sr-only"> (concluída)</span>}
            {!now && <span aria-hidden className="mx-1 text-line">—</span>}
          </li>
        );
      })}
    </ol>
  );
}
