import type { ReactNode } from "react";

// Renderer mínimo e SEGURO (React escapa tudo; sem HTML cru). Suporta: # ## ###, listas, **negrito**, `código`, imagens ![alt](assets/...).
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(!\[([^\]]*)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|`([^`]+)`)/g;
  let last = 0, k = 0, m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[2] !== undefined) {
      const rel = m[3].replace(/^(\.\/|\.\.\/)+/, "").replace(/^assets\//, "");
      const ok = /^[a-z0-9][a-z0-9/.-]*\.png$/.test(rel) && !rel.includes("..");
      out.push(ok ? <img key={k++} src={`/ajuda-assets/${rel}`} alt={m[2]} className="my-3 max-w-full rounded-card border border-line" loading="lazy" /> : null);
    } else if (m[4] !== undefined) out.push(<strong key={k++}>{m[4]}</strong>);
    else out.push(<code key={k++} className="rounded bg-bg px-1">{m[5]}</code>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/<!--[\s\S]*?-->/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    blocks.push(<Tag key={blocks.length} className={`my-3 space-y-1 pl-6 ${list.ordered ? "list-decimal" : "list-disc"}`}>{list.items.map((i, n) => <li key={n}>{inline(i)}</li>)}</Tag>);
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let m: RegExpExecArray | null;
    if ((m = /^(#{1,3})\s+(.*)$/.exec(line))) {
      flush();
      const cls = ["", "text-2xl font-semibold mt-2", "text-xl font-semibold mt-6", "text-lg font-semibold mt-4"][m[1].length];
      blocks.push(m[1].length === 1 ? <h2 key={blocks.length} className={cls}>{inline(m[2])}</h2> : m[1].length === 2 ? <h3 key={blocks.length} className={cls}>{inline(m[2])}</h3> : <h4 key={blocks.length} className={cls}>{inline(m[2])}</h4>);
    } else if ((m = /^\s*(\d+)\.\s+(.*)$/.exec(line))) { if (!list || !list.ordered) { flush(); list = { ordered: true, items: [] }; } list.items.push(m[2]); }
    else if ((m = /^\s*[-*]\s+(.*)$/.exec(line))) { if (!list || list.ordered) { flush(); list = { ordered: false, items: [] }; } list.items.push(m[1]); }
    else if (line.trim() === "") flush();
    else { flush(); blocks.push(<p key={blocks.length} className="my-3">{inline(line)}</p>); }
  }
  flush();
  return <>{blocks}</>;
}
