// Centro de OLT (ADR-0046): regras PURAS da conexão da OLT (sem React, sem rede): presets de porta, validação de IP e da impressão digital do host, máscara do endereço (idêntica à da API),
// o texto claro do kind `olt_connection` (ADR-0046 D4) e a prontidão em português. Só `import type` de oltSeal (nenhum ciclo em tempo de execução).
import type { ConnectionPlain } from "./oltSeal";

export const PROTOCOLS: [string, string][] = [["ssh", "SSH"], ["telnet", "Telnet (só cadastro)"]];
export const TRANSPORTS: [string, string][] = [["cli", "Linha de comando (SSH)"], ["snmp", "SNMP"]];
export const SSH_MODES: [string, string][] = [["exec", "exec (um comando por sessão)"], ["shell", "shell (sessão interativa)"]];
export const DEFAULT_PORT: Record<string, number> = { ssh: 22, telnet: 23 };
export const DEFAULT_SNMP_PORT = 161;
/** O Edge hoje só opera estes fabricantes; os demais ficam como inventário (a nuvem não bloqueia o envio: quem responde é o Edge). */
export const EDGE_VENDORS = ["huawei", "zte"];
export const VENDOR_WARNING = "O Edge hoje só opera Huawei e ZTE; os demais ficam como inventário (o Edge recusa a conexão deste fabricante).";
export const TELNET_WARNING = "Telnet é só inventário: a OLT fica cadastrada, mas nenhuma conexão nem senha é entregue ao Edge (o Telnet trafega em texto puro). Não há campo de senha nem de community para Telnet.";
export const HOST_KEY_HELP = "ssh-keyscan -t rsa IP | ssh-keygen -lf -";
/** O comando que quem administra o Edge roda NO SERVIDOR DO EDGE para confiar no host (ADR-0046 D4). */
export const TRUST_COMMAND = (oltName: string) => `fibercore-edge managed-trust ${shellQuote(oltName)}`;
function shellQuote(s: string): string {
  return /^[A-Za-z0-9._@%+=:,/-]+$/.test(s) ? s : `'${s.replace(/'/g, "'\\''")}'`;
}

export const defaultPortFor = (protocol: string): number | null => DEFAULT_PORT[protocol] ?? null;

/** Porta: inteiro de 1 a 65535 (texto digitado). Devolve a mensagem em português ou null. */
export function portProblem(text: string): string | null {
  if (!/^[0-9]{1,5}$/.test(text.trim())) return "A porta é um número de 1 a 65535.";
  const n = Number(text);
  return n >= 1 && n <= 65535 ? null : "A porta é um número de 1 a 65535.";
}

/** Impressão digital do host SSH, como `ssh-keygen -lf` mostra: SHA256: + 43 caracteres base64 (mesmo formato do banco e do Edge). */
export const HOST_KEY_RE = /^SHA256:[A-Za-z0-9+/]{43}$/;
export function hostKeyProblem(v: string): string | null {
  return HOST_KEY_RE.test(v) ? null : "A impressão digital deve ser “SHA256:” seguida de 43 caracteres (o que ssh-keygen -lf mostra).";
}

function ipv4(s: string): number[] | null {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(s);
  if (!m) return null;
  const o = m.slice(1).map((x) => (x.length > 1 && x.startsWith("0") ? NaN : Number(x)));   // zeros à esquerda são recusados (como no Python)
  return o.every((n) => n >= 0 && n <= 255) ? o : null;
}
/** Oito grupos de 16 bits ou null. Sem zona (%), sem IPv4 embutido. */
function ipv6(s: string): number[] | null {
  if (!/^[0-9A-Fa-f:]+$/.test(s) || s.includes(":::")) return null;
  const parts = s.split("::");
  if (parts.length > 2) return null;
  const groups = (t: string) => (t === "" ? [] : t.split(":"));
  const head = groups(parts[0]), tail = parts.length === 2 ? groups(parts[1]) : [];
  if ([...head, ...tail].some((g) => !/^[0-9A-Fa-f]{1,4}$/.test(g))) return null;
  if (parts.length === 1 && head.length !== 8) return null;
  if (parts.length === 2 && head.length + tail.length > 7) return null;
  const fill = parts.length === 2 ? Array(8 - head.length - tail.length).fill("0") : [];
  return [...head, ...fill, ...tail].map((g) => parseInt(g, 16));
}

/** Mesma regra de core/fleet.address_problem: IP literal (v4 ou v6), sem porta, máscara nem nome; sem endereço especial. Nunca repete o valor. */
export function ipLiteralProblem(raw: string): string | null {
  const v = raw.trim();
  const a = ipv4(v), b = a ? null : ipv6(v);
  if (!a && !b) return "Informe um IP (IPv4 ou IPv6), sem nome, porta nem máscara.";
  if (a) {
    if (a.every((x) => x === 0) || a[0] === 127 || (a[0] >= 224 && a[0] <= 239) || (a[0] === 169 && a[1] === 254)) return "Este não é um endereço de gerência utilizável.";
  } else if (b) {
    const unspecified = b.every((x) => x === 0), loopback = b.slice(0, 7).every((x) => x === 0) && b[7] === 1;
    if (unspecified || loopback || (b[0] & 0xff00) === 0xff00 || (b[0] & 0xffc0) === 0xfe80) return "Este não é um endereço de gerência utilizável.";
  }
  return null;
}

/** O que a API devolve do endereço (core/fleet.mask_address): IPv4 `a.b.•.•`; IPv6 o primeiro grupo (4 dígitos) e `:•` ×7. Entrada já validada. */
export function maskAddress(raw: string): string | null {
  const v = raw.trim();
  const a = ipv4(v);
  if (a) return `${a[0]}.${a[1]}.•.•`;
  const b = ipv6(v);
  return b ? `${b[0].toString(16).padStart(4, "0")}:•:•:•:•:•:•:•` : null;
}

/** O endereço redigitado tem de ter a MESMA máscara do que a nuvem guardou: pega erro de digitação antes de selar, sem a nuvem devolver o endereço. */
export function addressMatchesMask(typed: string, masked: string | null): boolean {
  return masked !== null && maskAddress(typed) === masked;
}

export type ConnView = {
  protocol: string | null; port: number | null; transport: string | null; snmp_port: number | null; host_key_sha256: string | null;
  ssh_mode: string | null; legacy_ssh: boolean; trust_state: string; applied: boolean; applied_at: string | null;
};

/** O texto claro do kind `olt_connection` (ADR-0046 D4), na ordem do ADR. `snmp_port` sempre presente (161 se vazio) e `ssh_mode` "exec" se vazio. Devolve a mensagem em português se a OLT ainda não tem o que o Edge exige. */
export function connectionPlain(olt: { id: string; vendor: string; connection: ConnView }, address: string): { plain: ConnectionPlain } | { problem: string } {
  const c = olt.connection;
  if (c.protocol !== "ssh") return { problem: "Só uma OLT com protocolo SSH recebe a conexão: Telnet é só cadastro." };
  if (c.port === null) return { problem: "Falta a porta da OLT no cadastro." };
  if (c.host_key_sha256 === null) return { problem: "Falta a impressão digital do host SSH no cadastro. Obtenha-a com " + HOST_KEY_HELP + " e salve no cadastro." };
  const bad = ipLiteralProblem(address);
  if (bad) return { problem: bad };
  return {
    plain: {
      kind: "olt_connection", action: "set", address: address.trim(), port: c.port, protocol: "ssh", vendor: olt.vendor, transport: c.transport === "snmp" ? "snmp" : "cli",
      snmp_port: c.snmp_port ?? DEFAULT_SNMP_PORT, host_key_sha256: c.host_key_sha256, legacy_ssh: c.legacy_ssh, ssh_mode: c.ssh_mode === "shell" ? "shell" : "exec", cloud_id: olt.id,
    },
  };
}

// ---- prontidão (ADR-0046 D3)
export type Readiness = { managed: boolean; stage: string; steps: { connection: boolean; trust: string; credential: boolean; tested: boolean } };
export const STAGE_PT: Record<string, string> = {
  registered: "Cadastrada", telnet_inventory: "Aguardando suporte a Telnet (só cadastro)", connection_applied: "Conexão aplicada", awaiting_trust: "Aguardando confirmação no Edge",
  trusted: "Confirmada no Edge (falta a credencial)", credential_applied: "Credencial aplicada", tested: "Testada",
};
export const stageText = (r: Readiness) => (r.managed ? STAGE_PT[r.stage] ?? r.stage : "Cadastro simples (o Edge usa a configuração dele)");

export type StepState = "done" | "current" | "pending";
/** A cadeia exibida: Cadastrada → Conexão aplicada → Confirmação no Edge → Credencial aplicada → Testada. O primeiro item ainda não alcançado é o "current". Telnet e cadastro simples não têm cadeia. */
export function readinessSteps(r: Readiness): { key: string; label: string; state: StepState }[] | null {
  if (!r.managed || r.stage === "telnet_inventory") return null;
  const at = ["registered", "connection_applied", "awaiting_trust", "trusted", "credential_applied", "tested"].indexOf(r.stage);
  const items = [
    { key: "registered", label: "Cadastrada", done: true },
    { key: "connection", label: "Conexão aplicada", done: at >= 1 },
    { key: "trust", label: at >= 3 ? "Confirmada no Edge" : r.stage === "awaiting_trust" ? "Aguardando confirmação no Edge" : "Confirmação no Edge", done: at >= 3 },
    { key: "credential", label: "Credencial aplicada", done: at >= 4 },
    { key: "tested", label: "Testada", done: at >= 5 },
  ];
  const first = items.findIndex((i) => !i.done);
  return items.map((i, n) => ({ key: i.key, label: i.label, state: i.done ? "done" : n === first ? "current" : "pending" }));
}
