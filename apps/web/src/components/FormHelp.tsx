/** Ajuda de um formulário recolhida por padrão: os textos longos saem de baixo de cada campo e ficam num único bloco que a pessoa abre quando precisa. Funciona sem JavaScript (<details>). */
export function FormHelp({ children, label = "Ajuda sobre os campos", testId }: { children: React.ReactNode; label?: string; testId?: string }) {
  return (
    <details className="text-xs text-muted md:col-span-6" data-testid={testId}>
      <summary className="inline-flex min-h-[28px] cursor-pointer select-none items-center text-accent">{label}</summary>
      <div className="mt-1 grid gap-1.5 rounded-btn border border-line px-3 py-2">{children}</div>
    </details>
  );
}
