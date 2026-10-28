import "server-only";
import fs from "node:fs";
import path from "node:path";

// Somente docs/help é servido: nunca docs/architecture, agentes ou prompts.
export const HELP_DIR = path.resolve(process.env.HELP_DIR ?? path.join(process.cwd(), "..", "..", "docs", "help"));
const SEG = /^[a-z0-9][a-z0-9-]*$/;

export type Article = { slug: string; title: string; status: string; body: string; meta: Record<string, string> };

export function safeSlug(parts: string[]): string | null {
  return parts.length >= 1 && parts.length <= 3 && parts.every((p) => SEG.test(p)) ? parts.join("/") : null;
}

function parse(raw: string): { meta: Record<string, string>; body: string } {
  const m = /^---\n([\s\S]*?)\n---\n?/.exec(raw);
  const meta: Record<string, string> = {};
  if (m) for (const line of m[1].split("\n")) { const i = line.indexOf(":"); if (i > 0) meta[line.slice(0, i).trim()] = line.slice(i + 1).trim().replace(/^"|"$/g, ""); }
  return { meta, body: m ? raw.slice(m[0].length) : raw };
}

export function listArticles(): Article[] {
  const root = path.join(HELP_DIR, "how-to");
  const out: Article[] = [];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.name.endsWith(".md")) {
        const slug = path.relative(root, p).replace(/\.md$/, "").split(path.sep).join("/");
        const { meta, body } = parse(fs.readFileSync(p, "utf8"));
        out.push({ slug, title: meta.title ?? slug, status: meta.status ?? "draft", body, meta });
      }
    }
  };
  walk(root);
  return out.sort((a, b) => a.title.localeCompare(b.title, "pt-BR"));
}

export function getArticle(slug: string): Article | null {
  return listArticles().find((a) => a.slug === slug) ?? null;
}

export function searchArticles(q: string): Article[] {
  const n = q.trim().toLowerCase();
  const all = listArticles();
  return n ? all.filter((a) => (a.title + " " + a.body).toLowerCase().includes(n)) : all;
}

export function assetPath(parts: string[]): string | null {
  if (!parts.length || parts.length > 4 || !parts.every((p) => /^[a-z0-9][a-z0-9.-]*$/.test(p))) return null;
  const full = path.resolve(HELP_DIR, "assets", ...parts);
  if (!full.startsWith(path.join(HELP_DIR, "assets") + path.sep) || !full.endsWith(".png")) return null;
  return fs.existsSync(full) ? full : null;
}
