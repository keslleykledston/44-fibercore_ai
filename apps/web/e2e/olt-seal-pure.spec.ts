import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { aadFor, b64urlDecode, b64urlEncode, fingerprintOf, keyIdOf, plainJson, plainProblem, sealOltSecret, type Plain } from "../src/lib/oltSeal";

// Selagem no navegador (ADR-0045): reproduz BYTE A BYTE os vetores gerados por implementação independente (Python `cryptography`) e abre o que sela com a chave do Edge de teste. Funções puras: sem navegador nem API.
const V = JSON.parse(readFileSync(resolve(__dirname, "../../../docs/addenda/olt-secrets/vectors.json"), "utf8"));
const subtle = globalThis.crypto.subtle;
const hexBytes = (h: string) => Uint8Array.from(h.match(/../g)!.map((x) => parseInt(x, 16)));

async function ephemeralFrom(scalarHex: string, expectedBlob: Uint8Array) {
  const publicRaw = expectedBlob.slice(1, 66);   // o vetor traz a pública efêmera dentro do blob; a privada vem do escalar fixo
  const jwk = { kty: "EC", crv: "P-256", d: b64urlEncode(hexBytes(scalarHex)), x: b64urlEncode(publicRaw.slice(1, 33)), y: b64urlEncode(publicRaw.slice(33, 65)), ext: true };
  return { privateKey: await subtle.importKey("jwk", jwk, { name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]), publicRaw };
}
async function edgePrivate() {
  const pub = b64urlDecode(V.edge.public_point_b64url);
  const jwk = { kty: "EC", crv: "P-256", d: b64urlEncode(hexBytes(V.edge.private_scalar_hex)), x: b64urlEncode(pub.slice(1, 33)), y: b64urlEncode(pub.slice(33, 65)), ext: true };
  return subtle.importKey("jwk", jwk, { name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
}
/** O que o Edge faz (aqui em WebCrypto): ECDH com a efêmera do blob, HKDF, AES-GCM com a AAD. Lança se qualquer byte ou a AAD mudar. */
async function open(blob: Uint8Array, aad: string, keyId: string): Promise<string> {
  const eph = await subtle.importKey("raw", blob.slice(1, 66) as BufferSource, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const shared = await subtle.deriveBits({ name: "ECDH", public: eph }, await edgePrivate(), 256);
  const aes = await subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: new Uint8Array(0), info: new TextEncoder().encode(`fibercore-seal-v1|${keyId}`) }, await subtle.importKey("raw", shared, "HKDF", false, ["deriveKey"]), { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  return new TextDecoder().decode(await subtle.decrypt({ name: "AES-GCM", iv: blob.slice(66, 78) as BufferSource, additionalData: new TextEncoder().encode(aad), tagLength: 128 }, aes, blob.slice(78) as BufferSource));
}
function inputOf(c: { aad: string; kind: string; plaintext_json: string }) {
  const p = c.aad.split("\n");
  const plain = JSON.parse(c.plaintext_json) as Plain;
  return { tenantId: p[1], edgeId: p[2], oltName: p[3], deliveryId: p[5], keyId: p[6], expiresAtUnix: Number(p[7]), edgePublicKey: V.edge.public_point_b64url, plain };
}

test("chave do Edge: key_id e impressão digital batem com o vetor, calculados no navegador", async () => {
  expect(await keyIdOf(V.edge.public_point_b64url)).toBe(V.edge.key_id);
  expect(await fingerprintOf(V.edge.public_point_b64url)).toBe(V.edge.fingerprint);
  await expect(keyIdOf(b64urlEncode(new Uint8Array(65)))).rejects.toThrow();            // não é um ponto não comprimido
  await expect(keyIdOf(V.edge.public_point_b64url.slice(0, 80))).rejects.toThrow();
});

for (const [idx, c] of (V.cases as { aad: string; kind: string; plaintext_json: string; sealed_b64url: string; blob_len: number }[]).entries()) {
  test(`vetor ${idx} (${c.kind}): a selagem com efêmera e nonce fixos reproduz o blob byte a byte, a AAD e o JSON`, async () => {
    const expected = b64urlDecode(c.sealed_b64url);
    const i = inputOf(c);
    expect(aadFor({ ...i, kind: i.plain.kind })).toBe(c.aad);
    expect(plainJson(i.plain)).toBe(c.plaintext_json);
    const r = await sealOltSecret(i, { ephemeral: await ephemeralFrom(V.ephemeral.private_scalar_hex, expected), nonce: hexBytes(V.ephemeral.nonce_hex) });
    expect(r.sealed).toBe(c.sealed_b64url);
    expect(r.blob.length).toBe(c.blob_len);
    expect(await open(r.blob, c.aad, V.edge.key_id)).toBe(c.plaintext_json);          // e o Edge (aqui, WebCrypto) abre
  });
}

test("o vetor independente também abre com o código de teste (decifrar o que o Python cifrou)", async () => {
  const c = V.cases[0];
  expect(await open(b64urlDecode(c.sealed_b64url), c.aad, V.edge.key_id)).toBe(c.plaintext_json);
});

test("sem injeção: cada selagem usa efêmera e nonce novos, abre com a AAD certa e NÃO abre com outra", async () => {
  const i = inputOf(V.cases[0]);
  const a = await sealOltSecret(i), b = await sealOltSecret(i);
  expect(a.sealed).not.toBe(b.sealed);
  expect(a.blob.slice(1, 66)).not.toEqual(b.blob.slice(1, 66));   // efêmera nova
  expect(a.blob.slice(66, 78)).not.toEqual(b.blob.slice(66, 78)); // nonce novo
  expect(a.blob[0]).toBe(1);
  expect(a.sealed).toMatch(/^[A-Za-z0-9_-]+$/);
  expect(a.sealed.length).toBeLessThanOrEqual(2048);
  expect(await open(a.blob, a.aad, i.keyId)).toBe(V.cases[0].plaintext_json);
  for (const bad of [a.aad.replace("OLT-CENTRO-01", "OLT-CENTRO-02"), a.aad.replace("ssh_login", "snmp_community"), a.aad.replace(/\n1893456000$/, "\n1893456001"), a.aad.replace("\n33333333", "\n44444444")]) {
    await expect(open(a.blob, bad, i.keyId)).rejects.toThrow();
  }
  const tampered = a.blob.slice(); tampered[tampered.length - 1] ^= 1;
  await expect(open(tampered, a.aad, i.keyId)).rejects.toThrow();
});

test("falha fechada: key_id que não é o da chave, chave inválida e texto claro fora dos limites; a mensagem não repete o valor", async () => {
  const i = inputOf(V.cases[0]);
  await expect(sealOltSecret({ ...i, keyId: "0".repeat(16) })).rejects.toThrow(/key_id/);
  await expect(sealOltSecret({ ...i, edgePublicKey: b64urlEncode(new Uint8Array(65)) })).rejects.toThrow();
  const secret = "SEGREDO-NAO-VAZA-" + "x".repeat(200);
  const err = await sealOltSecret({ ...i, plain: { kind: "ssh_login", username: "admin", password: secret } }).catch((e: Error) => e);
  expect(err).toBeInstanceOf(Error);
  expect((err as Error).message).not.toContain("SEGREDO");
});

test("limites e proibições do ADR: vazio, \\r \\n \\0, bytes UTF-8 acima do limite", () => {
  const ok: Plain = { kind: "ssh_login", username: "u".repeat(64), password: "p".repeat(128) };
  expect(plainProblem(ok)).toBeNull();
  expect(plainProblem({ ...ok, username: "u".repeat(65) })).toMatch(/limite de 64/);
  expect(plainProblem({ ...ok, password: "p".repeat(129) })).toMatch(/limite de 128/);
  expect(plainProblem({ ...ok, password: "ç".repeat(65) })).toMatch(/limite de 128/);      // 130 bytes UTF-8
  expect(plainProblem({ ...ok, username: "" })).toMatch(/obrigatório/);
  for (const bad of ["a\nb", "a\rb", "a\0b"]) {
    expect(plainProblem({ ...ok, password: bad })).toMatch(/quebra de linha/);
    expect(plainProblem({ kind: "snmp_community", community: bad })).toMatch(/quebra de linha/);
  }
  expect(plainProblem({ kind: "snmp_community", community: "c".repeat(64) })).toBeNull();
  expect(plainProblem({ kind: "snmp_community", community: "c".repeat(65) })).toMatch(/limite de 64/);
  expect(plainProblem({ kind: "snmp_community", community: "" })).toMatch(/obrigatório/);
});
