"use client";
import { useEffect, useState } from "react";
import { Icon } from "./Icon";

// Escolha manual persistida só como conveniência do navegador; sem ela vale prefers-color-scheme.
export function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => {
    const t = document.documentElement.getAttribute("data-theme");
    setDark(t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches);
  }, []);
  function toggle() {
    const next = dark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("fc-theme", next); } catch { /* armazenamento indisponível */ }
    setDark(!dark);
  }
  return (
    <button type="button" onClick={toggle} aria-label={dark ? "Usar tema claro" : "Usar tema escuro"}
      className="flex min-h-touch min-w-touch items-center justify-center rounded-btn text-muted hover:bg-surface-2">
      <Icon name={dark ? "sun" : "moon"} />
    </button>
  );
}
