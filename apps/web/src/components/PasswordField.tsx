"use client";

import { useId, useState } from "react";

/** Régua de força simples e honesta: o que conta é o tamanho (mínimo 12). Mostra os requisitos, nunca só cor. */
export function strength(pw: string): { label: string; level: 0 | 1 | 2 | 3; ok: boolean } {
  if (pw.length === 0) return { label: "", level: 0, ok: false };
  if (pw.length < 12) return { label: "Curta demais", level: 1, ok: false };
  if (pw.length < 16 || new Set(pw).size < 7) return { label: "Boa", level: 2, ok: true };
  return { label: "Forte", level: 3, ok: true };
}

export function PasswordField({ name, label, value, onChange, autoComplete, showStrength = false }: {
  name: string; label: string; value: string; onChange: (v: string) => void; autoComplete: string; showStrength?: boolean;
}) {
  const id = useId();
  const [show, setShow] = useState(false);
  const s = strength(value);
  return (
    <div className="grid gap-1">
      <label htmlFor={id}>{label}</label>
      <div className="flex gap-2">
        <input id={id} name={name} type={show ? "text" : "password"} required value={value} onChange={(e) => onChange(e.target.value)} autoComplete={autoComplete}
          aria-describedby={showStrength ? `${id}-rule` : undefined} className="min-h-touch min-w-0 flex-1 rounded-btn border border-line bg-bg px-3" />
        <button type="button" onClick={() => setShow((v) => !v)} aria-pressed={show} className="min-h-touch rounded-btn border border-line px-3 text-sm hover:bg-bg">{show ? "Ocultar" : "Mostrar"}</button>
      </div>
      {showStrength && (
        <div id={`${id}-rule`} className="text-xs text-muted" aria-live="polite">
          <div className="mt-1 flex gap-1" aria-hidden>{[1, 2, 3].map((n) => <span key={n} className={`h-1.5 flex-1 rounded-full ${s.level >= n ? "bg-ok" : "bg-line"}`} />)}</div>
          <span>Mínimo de 12 caracteres. Uma frase longa funciona melhor que símbolos. {s.label && <strong className="text-text">{s.label}.</strong>}</span>
        </div>
      )}
    </div>
  );
}
