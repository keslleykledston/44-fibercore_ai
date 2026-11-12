"use client";

import { useEffect, useRef, useState } from "react";

/**
 * O link do convite do primeiro administrador. O servidor só entrega o CAMINHO (`/convite/<token>`): a origem completa é a que o NAVEGADOR da pessoa usa agora (`window.location.origin`),
 * nunca um cabeçalho de host da requisição (um `X-Forwarded-Host` forjado levaria o token a outro domínio: Codex r2). Sem JavaScript o campo mostra só o caminho e a tela diz para
 * juntar o endereço desta plataforma; com JavaScript mostra o link inteiro e oferece copiar.
 */
export function OrgInviteLink({ path }: { path: string }) {
  const [origin, setOrigin] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => { setOrigin(window.location.origin); }, []);
  const value = origin ? `${origin}${path}` : path;
  async function copy() {
    try { await navigator.clipboard.writeText(value); setCopied(true); }
    catch { field.current?.select(); setCopied(document.execCommand?.("copy") ?? false); }
    setTimeout(() => setCopied(false), 4000);
  }
  return (
    <div className="grid gap-1 text-sm">
      <label htmlFor="org-convite-link">Link do convite (aparece só agora)</label>
      <div className="flex flex-wrap gap-2">
        <input id="org-convite-link" ref={field} readOnly value={value} onFocus={(e) => e.currentTarget.select()} data-testid="org-convite-link"
          className="min-h-touch min-w-0 flex-1 rounded-btn border border-line bg-bg px-3 font-mono text-xs" />
        {origin && <button type="button" onClick={() => void copy()} data-testid="org-convite-copiar" className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">{copied ? "Copiado" : "Copiar link"}</button>}
      </div>
      <p role="status" aria-live="polite" className="sr-only">{copied ? "Link copiado" : ""}</p>
      {!origin && <p className="text-xs text-muted" data-testid="org-convite-sem-js">Sem JavaScript esta tela mostra só o caminho: junte-o ao endereço desta plataforma (o mesmo que você usa no navegador) antes de enviar.</p>}
    </div>
  );
}
