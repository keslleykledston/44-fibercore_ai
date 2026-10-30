"use client";

import { useRef, useState } from "react";

/** Mostra UMA vez um link (convite ou troca de senha) com botão de copiar. O link não fica guardado em lugar nenhum; depois dá para gerar outro. */
export function SecretLink({ url, validity, title = "Link pronto" }: { url: string; validity: string; title?: string }) {
  const [copied, setCopied] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  async function copy() {
    try { await navigator.clipboard.writeText(url); setCopied(true); }
    catch { field.current?.select(); setCopied(document.execCommand?.("copy") ?? false); }
    setTimeout(() => setCopied(false), 4000);
  }
  return (
    <div className="grid gap-3 rounded-btn border border-line bg-bg p-4 text-sm" data-testid="secret-link">
      <p className="font-medium">{title}</p>
      <div className="flex flex-wrap gap-2">
        <input ref={field} readOnly value={url} aria-label="Link" onFocus={(e) => e.currentTarget.select()} data-testid="secret-link-url"
          className="min-h-touch min-w-0 flex-1 rounded-btn border border-line bg-surface px-3 font-mono text-xs" />
        <button type="button" onClick={() => void copy()} data-testid="secret-link-copy"
          className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">{copied ? "Copiado" : "Copiar link"}</button>
      </div>
      <p role="status" aria-live="polite" className="sr-only">{copied ? "Link copiado" : ""}</p>
      <ul className="list-disc pl-5 text-muted">
        <li>Envie por WhatsApp ou e-mail. Nada é enviado por este painel.</li>
        <li>Válido por {validity} e funciona uma vez só.</li>
        <li>O link aparece <strong>só agora</strong>. Se perder, gere outro.</li>
      </ul>
    </div>
  );
}
