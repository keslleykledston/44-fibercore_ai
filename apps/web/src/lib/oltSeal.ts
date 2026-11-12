// Selagem de credencial de OLT NO NAVEGADOR (ADR-0045). Funções PURAS e sem dependência de React/Next: rodam no navegador e em Node (teste puro contra docs/addenda/olt-secrets/vectors.json).
// O texto claro só existe dentro de `sealOltSecret`: ele sai daqui cifrado (ECDH P-256 + HKDF-SHA256 + AES-256-GCM) para a chave pública do Edge e nada mais o guarda, registra ou envia.
//
// Formato (contrato exato, interoperável com o Go do Edge):
//   chave do Edge = ponto P-256 não comprimido (65 bytes), base64url sem preenchimento; key_id = 16 primeiros hex de SHA-256(ponto); impressão digital = 32 primeiros hex em 8 grupos de 4 com "-"
//   AAD  = UTF-8 de "fibercore-seal-v1\n{tenant_id}\n{edge_id}\n{olt_name}\n{kind}\n{delivery_id}\n{key_id}\n{expires_at_unix}"
//   chave AES = HKDF-SHA256(ikm = ECDH(efêmera, edge), salt = vazio, info = "fibercore-seal-v1|" + key_id), 256 bits; nonce de 12 bytes aleatórios; AES-GCM com a AAD
//   blob = 0x01 ‖ efêmera_pub(65) ‖ nonce(12) ‖ texto cifrado‖tag, em base64url sem preenchimento

export type SecretKind = "ssh_login" | "snmp_community" | "olt_connection";
/** ADR-0046 D4: a CONEXÃO da OLT (não secreta, mas cifrada pelo mesmo canal). `remove` só leva kind, action e cloud_id. A ordem dos campos é a do ADR. */
export type ConnectionPlain =
  | { kind: "olt_connection"; action: "set"; address: string; port: number; protocol: "ssh"; vendor: string; transport: "cli" | "snmp"; snmp_port: number; host_key_sha256: string; legacy_ssh: boolean; ssh_mode: "exec" | "shell"; cloud_id: string }
  | { kind: "olt_connection"; action: "remove"; cloud_id: string };
export type Plain = { kind: "ssh_login"; username: string; password: string } | { kind: "snmp_community"; community: string } | ConnectionPlain;

import { hostKeyProblem, ipLiteralProblem, portProblem } from "./oltConnection";

export const SEAL_PREFIX = "fibercore-seal-v1";
export const MAX_BLOB_CHARS = 2048;
/** Limites do ADR em BYTES UTF-8 (a leitura mais restritiva entre bytes e caracteres): usuário ≤ 64, senha ≤ 128, community ≤ 64. */
export const LIMITS = { username: 64, password: 128, community: 64 } as const;

/** Erro de selagem com mensagem SEGURA para mostrar (em português, nunca com o valor digitado). */
export class SealError extends Error {}

const enc = new TextEncoder();

export function b64urlEncode(raw: Uint8Array): string {
  let bin = "";
  for (const b of raw) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
export function b64urlDecode(text: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]+$/.test(text) || text.length % 4 === 1) throw new SealError("Chave inválida (base64url).");
  const bin = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
const hex = (b: Uint8Array) => [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
const buf = (b: Uint8Array) => b as unknown as BufferSource;   // TS 5.9: Uint8Array<ArrayBufferLike> não casa com BufferSource; os dados são os mesmos

/** SHA-256 em hex do ponto (a base de key_id e da impressão digital). */
async function pointDigestHex(point: Uint8Array, subtle: SubtleCrypto): Promise<string> {
  return hex(new Uint8Array(await subtle.digest("SHA-256", buf(point))));
}
export function checkPoint(point: Uint8Array): void {
  if (point.length !== 65 || point[0] !== 0x04) throw new SealError("Chave do Edge inválida.");
}
export async function keyIdOf(publicKeyB64url: string, subtle: SubtleCrypto = globalThis.crypto.subtle): Promise<string> {
  const p = b64urlDecode(publicKeyB64url);
  checkPoint(p);
  return (await pointDigestHex(p, subtle)).slice(0, 16);
}
/** Impressão digital para humanos: 32 hex em 8 grupos de 4. Calculada AQUI, da chave que será usada para selar (não confia no que o servidor diz). */
export async function fingerprintOf(publicKeyB64url: string, subtle: SubtleCrypto = globalThis.crypto.subtle): Promise<string> {
  const p = b64urlDecode(publicKeyB64url);
  checkPoint(p);
  return ((await pointDigestHex(p, subtle)).slice(0, 32).match(/.{4}/g) as string[]).join("-");
}

export function aadFor(a: { tenantId: string; edgeId: string; oltName: string; kind: SecretKind; deliveryId: string; keyId: string; expiresAtUnix: number }): string {
  return [SEAL_PREFIX, a.tenantId.toLowerCase(), a.edgeId.toLowerCase(), a.oltName, a.kind, a.deliveryId.toLowerCase(), a.keyId, String(Math.trunc(a.expiresAtUnix))].join("\n");
}

const utf8 = (s: string) => enc.encode(s).length;
const clean = (s: string) => !/[\r\n\0]/.test(s);

/** Valida o texto claro (ADR): obrigatórios, sem \r \n \0, limites em bytes. Devolve uma mensagem em português (sem repetir o valor) ou null. */
export function plainProblem(p: Plain): string | null {
  if (p.kind === "olt_connection") return connectionProblem(p);
  const fields: [string, string, number][] = p.kind === "ssh_login" ? [["O login", p.username, LIMITS.username], ["A senha", p.password, LIMITS.password]] : [["A community", p.community, LIMITS.community]];
  for (const [label, v, max] of fields) {
    if (v.length === 0) return `${label} é obrigatório.`;
    if (!clean(v)) return `${label} não pode ter quebra de linha nem caractere nulo.`;
    if (utf8(v) > max) return `${label} passa do limite de ${max} bytes.`;
  }
  return null;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** ADR-0046 D4: o que o Edge valida (IP literal, porta, protocolo ssh, fabricante, impressão digital no formato, cloud_id). Mensagem em português sem repetir o valor, ou null. */
function connectionProblem(p: ConnectionPlain): string | null {
  if (!UUID_RE.test(p.cloud_id)) return "Identificador da OLT inválido.";
  if (p.action === "remove") return null;
  const ip = ipLiteralProblem(p.address);
  if (ip) return ip;
  const port = portProblem(String(p.port));
  if (port) return port;
  if (!Number.isInteger(p.snmp_port) || p.snmp_port < 1 || p.snmp_port > 65535) return "A porta SNMP é um número de 1 a 65535.";
  if (p.protocol !== "ssh") return "Só SSH recebe a conexão: Telnet é só cadastro.";
  if (!/^[a-z]{2,20}$/.test(p.vendor)) return "Fabricante inválido.";
  if (p.transport !== "cli" && p.transport !== "snmp") return "Transporte inválido.";
  if (p.ssh_mode !== "exec" && p.ssh_mode !== "shell") return "Modo SSH inválido.";
  return hostKeyProblem(p.host_key_sha256);
}

/** O JSON exato do ADR (ordem dos campos e sem espaços): é o que o Edge decifra e valida. */
export function plainJson(p: Plain): string {
  if (p.kind === "ssh_login") return JSON.stringify({ kind: p.kind, username: p.username, password: p.password });
  if (p.kind === "snmp_community") return JSON.stringify({ kind: p.kind, community: p.community });
  if (p.action === "remove") return JSON.stringify({ kind: p.kind, action: p.action, cloud_id: p.cloud_id });
  return JSON.stringify({ kind: p.kind, action: p.action, address: p.address, port: p.port, protocol: p.protocol, vendor: p.vendor, transport: p.transport, snmp_port: p.snmp_port,
    host_key_sha256: p.host_key_sha256, legacy_ssh: p.legacy_ssh, ssh_mode: p.ssh_mode, cloud_id: p.cloud_id });
}

export type SealDeps = {
  subtle?: SubtleCrypto;
  /** Só para teste (vetores): a efêmera e o nonce fixos. Em produção ficam ausentes e valem um par e um nonce novos a cada selagem. */
  ephemeral?: { privateKey: CryptoKey; publicRaw: Uint8Array };
  nonce?: Uint8Array;
  getRandomValues?: (a: Uint8Array) => Uint8Array;
};
export type SealInput = { tenantId: string; edgeId: string; oltName: string; deliveryId: string; keyId: string; expiresAtUnix: number; edgePublicKey: string; plain: Plain };

/** Sela. Falha fechada: chave inválida, key_id que não é o da chave, texto claro fora dos limites ou blob acima do limite lançam erro (sem repetir o valor). */
export async function sealOltSecret(i: SealInput, deps: SealDeps = {}): Promise<{ sealed: string; blob: Uint8Array; aad: string }> {
  const subtle = deps.subtle ?? globalThis.crypto.subtle;
  const rnd = deps.getRandomValues ?? ((a: Uint8Array) => globalThis.crypto.getRandomValues(a as Uint8Array<ArrayBuffer>));
  const problem = plainProblem(i.plain);
  if (problem) throw new SealError(problem);
  const edgePoint = b64urlDecode(i.edgePublicKey);
  checkPoint(edgePoint);
  if ((await keyIdOf(i.edgePublicKey, subtle)) !== i.keyId) throw new SealError("key_id não confere com a chave do Edge.");
  const aad = aadFor({ ...i, kind: i.plain.kind });
  const edgeKey = await subtle.importKey("raw", buf(edgePoint), { name: "ECDH", namedCurve: "P-256" }, false, []);
  let eph = deps.ephemeral;
  if (!eph) {
    const pair = await subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);   // a privada não é extraível; a pública sempre é
    eph = { privateKey: pair.privateKey, publicRaw: new Uint8Array(await subtle.exportKey("raw", pair.publicKey)) };   // a efêmera NOVA a cada selagem: chave AES única por mensagem
  }
  const shared = await subtle.deriveBits({ name: "ECDH", public: edgeKey }, eph.privateKey, 256);
  const hkdfKey = await subtle.importKey("raw", shared, "HKDF", false, ["deriveKey"]);
  const aes = await subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: buf(new Uint8Array(0)), info: buf(enc.encode(`${SEAL_PREFIX}|${i.keyId}`)) }, hkdfKey, { name: "AES-GCM", length: 256 }, false, ["encrypt"]);
  const nonce = deps.nonce ?? rnd(new Uint8Array(12));
  if (nonce.length !== 12) throw new SealError("nonce inválido");
  const ct = new Uint8Array(await subtle.encrypt({ name: "AES-GCM", iv: buf(nonce), additionalData: buf(enc.encode(aad)), tagLength: 128 }, aes, buf(enc.encode(plainJson(i.plain)))));
  const blob = new Uint8Array(1 + 65 + 12 + ct.length);
  blob[0] = 0x01;
  blob.set(eph.publicRaw, 1);
  blob.set(nonce, 66);
  blob.set(ct, 78);
  const sealed = b64urlEncode(blob);
  if (sealed.length > MAX_BLOB_CHARS) throw new SealError("O conteúdo cifrado passa do limite de tamanho.");
  return { sealed, blob, aad };
}
