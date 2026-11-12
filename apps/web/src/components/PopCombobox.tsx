"use client";
import { useId, useState } from "react";
import { popChoice } from "@/lib/fleet";

type PopItem = { id: string; name: string };

/**
 * Site (POP) com criação ao digitar. O campo de texto se chama `pop_name` (sem JavaScript o servidor ainda casa o nome ou cria o site); com JavaScript, escolher um site existente
 * preenche `pop_id`. Se o nome digitado não casa com nenhum, aparece a opção "Adicionar “X” como novo site" e o site é criado junto com o cadastro (na mesma requisição).
 */
export function PopCombobox({ pops, defaultName = "", label = "Site / POP", testId = "pop-combobox" }: { pops: PopItem[]; defaultName?: string; label?: string; testId?: string }) {
  const base = useId();
  const [text, setText] = useState(defaultName);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const choice = popChoice(text, pops);
  const options: { key: string; label: string; add?: boolean; pick: () => void }[] = [
    ...choice.matches.slice(0, 8).map((p) => ({ key: p.id, label: p.name, pick: () => { setText(p.name); setOpen(false); } })),
    ...(choice.create ? [{ key: "__new", label: `Adicionar “${choice.typed}” como novo site`, add: true, pick: () => { setText(choice.typed); setOpen(false); } }] : []),
  ];
  const listId = `${base}-list`;
  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => (options.length ? (a + 1) % options.length : -1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setOpen(true); setActive((a) => (options.length ? (a <= 0 ? options.length - 1 : a - 1) : -1)); }
    else if (e.key === "Enter" && open && active >= 0 && options[active]) { e.preventDefault(); options[active].pick(); }   // só captura o Enter quando uma opção está realçada; fora disso o formulário envia normalmente
    else if (e.key === "Escape" && open) { e.preventDefault(); setOpen(false); }
  }
  return (
    <div className="relative grid gap-1 text-sm" data-testid={testId}>
      <label htmlFor={`${base}-in`}>{label}</label>
      <input id={`${base}-in`} name="pop_name" value={text} maxLength={60} autoComplete="off" spellCheck={false} role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={active >= 0 && options[active] ? `${base}-o${active}` : undefined} placeholder="Digite para buscar ou criar um site"
        onChange={(e) => { setText(e.target.value); setOpen(true); setActive(-1); }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 120)} onKeyDown={onKey}
        className="min-h-touch rounded-btn border border-line bg-bg px-3" />
      <input type="hidden" name="pop_id" value={choice.id ?? ""} />
      {/* a lista existe sempre (aria-controls precisa de um alvo válido) e fica oculta quando fechada */}
      <ul id={listId} role="listbox" aria-label="Sugestões de site" hidden={!(open && options.length > 0)} className="absolute left-0 right-0 top-full z-20 mt-1 max-h-56 overflow-auto rounded-btn border border-line bg-surface shadow">
          {options.map((o, i) => (
            <li key={o.key} id={`${base}-o${i}`} role="option" aria-selected={i === active} data-testid={o.add ? "pop-adicionar" : "pop-opcao"}
              onMouseDown={(e) => { e.preventDefault(); o.pick(); }} className={`flex min-h-touch cursor-pointer items-center px-3 py-2 ${i === active ? "bg-surface-2" : ""} ${o.add ? "font-medium text-accent" : ""}`}>{o.label}</li>))}
      </ul>
      <span className="text-xs text-muted" data-testid="pop-estado" aria-live="polite">
        {!text.trim() ? "Sem site." : choice.id ? "Site existente." : choice.create ? `Novo site: “${choice.typed}” será criado ao salvar.` : ""}
      </span>
    </div>
  );
}
