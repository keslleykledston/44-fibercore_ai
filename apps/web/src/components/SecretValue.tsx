"use client";

import { useRef, useState } from "react";

/** Mostra UMA vez um segredo que não é link (token de API, segredo de webhook). Só vive na memória desta tela: nada é gravado, nada vai para o histórico. */
export function SecretValue({ value, title, hint }: { value: string; title: string; hint?: string }) {
  const [copied, setCopied] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  async function copy() {
    try { await navigator.clipboard.writeText(value); setCopied(true); }
    catch { field.current?.select(); setCopied(document.execCommand?.("copy") ?? false); }
    setTimeout(() => setCopied(false), 4000);
  }
  return (
    <div className="grid gap-3 rounded-btn border border-warn bg-bg p-4 text-sm" data-testid="secret-value">
      <p className="font-medium">{title}</p>
      <div className="flex flex-wrap gap-2">
        <input ref={field} readOnly value={value} aria-label={title} autoComplete="off" onFocus={(e) => e.currentTarget.select()} data-testid="secret-value-text"
          className="min-h-touch min-w-0 flex-1 rounded-btn border border-line bg-surface px-3 font-mono text-xs" />
        <button type="button" onClick={() => void copy()} data-testid="secret-value-copy" className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">{copied ? "Copiado" : "Copiar"}</button>
      </div>
      <p role="status" aria-live="polite" className="sr-only">{copied ? "Copiado" : ""}</p>
      <ul className="list-disc pl-5 text-muted">
        <li>Aparece <strong>só agora</strong>. Guarde num cofre de senhas; depois não dá para ver de novo.</li>
        {hint && <li>{hint}</li>}
      </ul>
    </div>
  );
}
