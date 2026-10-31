import type { KeyboardEvent } from "react";

/** Navegação por teclado dos padrões ARIA de abas e grupo de opções (foco "roving"): setas movem e selecionam, Home/End vão às pontas; só o item ativo fica na sequência de Tab.
 *  Usar no `onKeyDown` de cada botão, com a posição dele (`index`) e a quantidade de itens; os botões precisam ser irmãos diretos, na ordem. */
export function rovingKeys(e: KeyboardEvent<HTMLElement>, index: number, count: number, go: (next: number) => void, orientation: "horizontal" | "both" = "both") {
  const k = e.key;
  const next = k === "ArrowRight" || (orientation === "both" && k === "ArrowDown") ? (index + 1) % count
    : k === "ArrowLeft" || (orientation === "both" && k === "ArrowUp") ? (index - 1 + count) % count
    : k === "Home" ? 0 : k === "End" ? count - 1 : -1;
  if (next < 0) return;
  e.preventDefault();
  go(next);
  (e.currentTarget.parentElement?.children[next] as HTMLElement | undefined)?.focus();
}
