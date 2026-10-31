/** Configuração do aparelho (ADR-0034, FC24-02): leitura dos formulários gerados pela API. Nada aqui escreve na rede; a API decide o que existe e o que é editável (hoje, nada). */
export type OntField = {
  name: string; instance_key: string; instance_label: string | null; label: string; input_type: "readonly"; editable: false; disabled_reason: string;
  unit: string | null; value: string | number | boolean | null; secret: boolean; source: string; quality: "fresh" | "stale"; captured_at: string;
};
export type OntGroup = { id: "wifi" | "lan" | "wan" | "optical"; title: string; read_only: boolean; fields: OntField[] };
export type OntInstance = { key: string; label: string; radio_binding?: string | null };
export type OntForm = {
  state: "no_data" | "fresh" | "partial_stale" | "stale"; synthetic: boolean; form_revision: string; help_slug: string;
  fingerprint: { vendor: string | null; model: string | null; firmware: string | null };
  groups: OntGroup[]; instances: { ssid: OntInstance[]; radio: OntInstance[] };
};

export const STATE_TEXT: Record<OntForm["state"], string> = {
  no_data: "Ainda não há leitura de configuração deste aparelho.",
  fresh: "Leitura recente.",
  partial_stale: "Alguns dados estão defasados (mais de 1 hora).",
  stale: "Nenhuma leitura nova há mais de 24 horas: a fonte parou de enviar.",
};
export const LOAD_ERROR: Record<string, string> = {
  disabled: "A configuração do aparelho está desligada para este provedor.",
  forbidden: "Seu papel não permite ver a configuração do aparelho.",
  not_found: "Este aparelho não existe mais.",
  session: "Sua sessão expirou. Recarregue a página e entre de novo.",
  failed: "Não foi possível carregar a configuração agora. Isso não significa que o aparelho não tenha dados.",
};

const NAME = /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$/;
const INST = /^[a-z]{3,10}\/[0-9]{1,3}$/;
const SHORT = /^[^\x00-\x1f\x7f]{0,120}$/;

/** Só devolve o formulário se TEM o formato fechado; qualquer campo fora dele derruba o conjunto (a tela nunca mostra o que não reconhece). */
export function readForm(d: unknown): OntForm | null {
  const o = d as OntForm | null;
  if (!o || typeof o !== "object" || !["no_data", "fresh", "partial_stale", "stale"].includes(o.state) || !Array.isArray(o.groups) || o.groups.length > 4) return null;
  const ok = o.groups.every((g) => ["wifi", "lan", "wan", "optical"].includes(g.id) && typeof g.title === "string" && SHORT.test(g.title) && Array.isArray(g.fields) && g.fields.length <= 120 &&
    g.fields.every((f) => NAME.test(f.name) && INST.test(f.instance_key) && typeof f.label === "string" && SHORT.test(f.label) && f.editable === false &&
      (f.value === null || ["string", "number", "boolean"].includes(typeof f.value)) && typeof f.disabled_reason === "string" && ["fresh", "stale"].includes(f.quality)));
  if (!ok || typeof o.form_revision !== "string" || !o.instances) return null;
  return { ...o, synthetic: o.synthetic === true };
}

export function valueText(f: OntField): string {
  if (f.value === null) return "—";
  if (typeof f.value === "boolean") return f.value ? "Ligado" : "Desligado";
  return `${f.value}${f.unit ? ` ${f.unit}` : ""}`;
}
