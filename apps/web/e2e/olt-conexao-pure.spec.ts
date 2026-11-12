import { createDecipheriv, createECDH, createHash, hkdfSync } from "node:crypto";
import { expect, test } from "@playwright/test";
import {
  addressMatchesMask, connectionPlain, defaultPortFor, hostKeyProblem, ipLiteralProblem, maskAddress, portProblem, readinessSteps, stageText, TRUST_COMMAND, type ConnView, type Readiness,
} from "../src/lib/oltConnection";
import { clearDraftAddress, peekDraftAddress, setDraftAddress } from "../src/lib/oltDraft";
import { aadFor, b64urlDecode, b64urlEncode, plainJson, plainProblem, sealOltSecret, type ConnectionPlain } from "../src/lib/oltSeal";

// Centro de OLT (ADR-0046): regras PURAS da conexão e a selagem do kind `olt_connection` no navegador (WebCrypto), aberta aqui com Node crypto (implementação independente). Sem navegador nem API.
const HK = "SHA256:" + createHash("sha256").update("fibercore-test-host").digest("base64").replace(/=+$/, "");
const OLT_ID = "3f2b8c1e-5a77-4d1e-9a0b-0c1d2e3f4a5b";
const conn = (over: Partial<ConnView> = {}): ConnView => ({ protocol: "ssh", port: 22, transport: "cli", snmp_port: null, host_key_sha256: HK, ssh_mode: "exec", legacy_ssh: false, trust_state: "none", applied: false, applied_at: null, ...over });

test("a máscara do endereço é idêntica à da API (core/fleet.mask_address)", () => {
  // os mesmos casos de apps/api/tests/test_fleet_register_fields.py e test_olt_center.py
  expect(maskAddress("10.20.30.40")).toBe("10.20.•.•");
  expect(maskAddress("10.77.88.99")).toBe("10.77.•.•");
  expect(maskAddress("100.64.9.205")).toBe("100.64.•.•");
  expect(maskAddress("2804:7ef4:803:9587::1")).toBe("2804:•:•:•:•:•:•:•");   // o primeiro grupo, expandido a 4 dígitos (ip.exploded)
  expect(maskAddress("2:1::1")).toBe("0002:•:•:•:•:•:•:•");
  expect(maskAddress("2001:DB8::1")).toBe("2001:•:•:•:•:•:•:•");
  expect(maskAddress("::2")).toBe("0000:•:•:•:•:•:•:•");
  expect(maskAddress(" 10.20.30.40 ")).toBe("10.20.•.•");
  expect(maskAddress("olt.example.com")).toBeNull();
  expect(addressMatchesMask("10.20.99.1", "10.20.•.•")).toBe(true);
  expect(addressMatchesMask("10.21.30.40", "10.20.•.•")).toBe(false);          // erro de digitação: máscara diferente
  expect(addressMatchesMask("10.20.30.40", null)).toBe(false);
});

test("IP literal: as mesmas recusas do servidor e nenhuma mensagem repete o valor", () => {
  for (const ok of ["10.20.30.40", "100.64.9.205", "2804:7ef4:803:9587::1", "192.168.0.1", "2001:db8::1"]) expect(ipLiteralProblem(ok), ok).toBeNull();
  for (const bad of ["olt.example.com", "10.0.0.1:22", "10.0.0.0/24", "999.1.1.1", "0.0.0.0", "127.0.0.1", "224.0.0.1", "169.254.1.1", "::1", "::", "", "10.0.0", "fe80::1", "ff02::1", "10.01.0.1", "1:2:3:4:5:6:7:8:9", "2001:db8::1::2", "fe80::1%eth0"]) {
    const why = ipLiteralProblem(bad);
    expect(why, bad).not.toBeNull();
    if (bad.length > 4) expect(why).not.toContain(bad);
  }
});

test("porta e impressão digital do host", () => {
  expect(defaultPortFor("ssh")).toBe(22);
  expect(defaultPortFor("telnet")).toBe(23);
  expect(defaultPortFor("")).toBeNull();
  for (const ok of ["1", "22", "2222", "65535"]) expect(portProblem(ok), ok).toBeNull();
  for (const bad of ["", "0", "65536", "-1", "22.5", "abc", "100000", " "]) expect(portProblem(bad), bad).not.toBeNull();
  expect(HK).toMatch(/^SHA256:[A-Za-z0-9+/]{43}$/);
  expect(hostKeyProblem(HK)).toBeNull();
  for (const bad of [HK + "A", HK.slice(0, -1), HK.replace("SHA256:", "MD5:"), "SHA256:" + "A".repeat(44), "sha256:" + HK.slice(7), "SHA256:" + "A".repeat(42) + "="]) expect(hostKeyProblem(bad), bad).not.toBeNull();
});

test("o texto claro do kind olt_connection é exatamente o do ADR-0046 D4 (ordem e valores)", () => {
  const r = connectionPlain({ id: OLT_ID, vendor: "huawei", connection: conn() }, "10.77.88.99");
  if ("problem" in r) throw new Error(r.problem);
  expect(plainJson(r.plain)).toBe(`{"kind":"olt_connection","action":"set","address":"10.77.88.99","port":22,"protocol":"ssh","vendor":"huawei","transport":"cli","snmp_port":161,"host_key_sha256":"${HK}","legacy_ssh":false,"ssh_mode":"exec","cloud_id":"${OLT_ID}"}`);
  const s = connectionPlain({ id: OLT_ID, vendor: "zte", connection: conn({ port: 2222, transport: "snmp", snmp_port: 1161, ssh_mode: "shell", legacy_ssh: true }) }, " 2804:7ef4:803:9587::1 ");
  if ("problem" in s) throw new Error(s.problem);
  expect(JSON.parse(plainJson(s.plain))).toEqual({ kind: "olt_connection", action: "set", address: "2804:7ef4:803:9587::1", port: 2222, protocol: "ssh", vendor: "zte", transport: "snmp", snmp_port: 1161, host_key_sha256: HK, legacy_ssh: true, ssh_mode: "shell", cloud_id: OLT_ID });
  expect(Object.keys(JSON.parse(plainJson(s.plain)))).toEqual(["kind", "action", "address", "port", "protocol", "vendor", "transport", "snmp_port", "host_key_sha256", "legacy_ssh", "ssh_mode", "cloud_id"]);
  const rm: ConnectionPlain = { kind: "olt_connection", action: "remove", cloud_id: OLT_ID };
  expect(plainJson(rm)).toBe(`{"kind":"olt_connection","action":"remove","cloud_id":"${OLT_ID}"}`);
  expect(plainProblem(rm)).toBeNull();
});

test("o que ainda falta na OLT ou no endereço vira mensagem em português e nada é montado", () => {
  const base = { id: OLT_ID, vendor: "huawei" };
  expect(connectionPlain({ ...base, connection: conn({ protocol: "telnet", host_key_sha256: null }) }, "10.0.0.1")).toEqual({ problem: expect.stringContaining("Telnet é só cadastro") });
  expect(connectionPlain({ ...base, connection: conn({ protocol: null }) }, "10.0.0.1")).toEqual({ problem: expect.stringContaining("SSH") });
  expect(connectionPlain({ ...base, connection: conn({ port: null }) }, "10.0.0.1")).toEqual({ problem: expect.stringContaining("porta") });
  expect(connectionPlain({ ...base, connection: conn({ host_key_sha256: null }) }, "10.0.0.1")).toEqual({ problem: expect.stringContaining("ssh-keyscan -t rsa IP | ssh-keygen -lf -") });
  expect(connectionPlain({ ...base, connection: conn() }, "olt.example.com")).toEqual({ problem: expect.stringContaining("IP") });
  const bad = { kind: "olt_connection", action: "set", address: "10.0.0.1", port: 22, protocol: "telnet", vendor: "huawei", transport: "cli", snmp_port: 161, host_key_sha256: HK, legacy_ssh: false, ssh_mode: "exec", cloud_id: OLT_ID } as unknown as ConnectionPlain;
  expect(plainProblem(bad)).toContain("Telnet");
  expect(plainProblem({ ...bad, protocol: "ssh", host_key_sha256: "SHA256:x" } as ConnectionPlain)).toContain("impressão digital");
  expect(plainProblem({ ...bad, protocol: "ssh", cloud_id: "x" } as ConnectionPlain)).toContain("OLT");
  expect(plainProblem({ ...bad, protocol: "ssh", port: 0 } as ConnectionPlain)).toContain("porta");
});

test("o comando de confiança no Edge e o rascunho do endereço (só memória)", () => {
  expect(TRUST_COMMAND("OLT-CENTRO-01")).toBe("fibercore-edge managed-trust OLT-CENTRO-01");
  expect(TRUST_COMMAND("OLT Centro 01")).toBe("fibercore-edge managed-trust 'OLT Centro 01'");   // nome com espaço: citado, para colar no shell
  expect(TRUST_COMMAND("x'; rm -rf /")).toBe(`fibercore-edge managed-trust 'x'\\''; rm -rf /'`);
  setDraftAddress("a", " 10.0.0.1 ");
  expect(peekDraftAddress("a")).toBe("10.0.0.1");
  expect(peekDraftAddress("b")).toBeNull();
  setDraftAddress("b", "10.0.0.2");                                              // no máximo um rascunho por vez
  expect(peekDraftAddress("a")).toBeNull();
  clearDraftAddress("b");
  expect(peekDraftAddress("b")).toBeNull();
});

test("prontidão: a cadeia Cadastrada → Conexão aplicada → Confirmação → Credencial → Testada, com o estado atual", () => {
  const r = (stage: string, over: Partial<Readiness> = {}): Readiness => ({ managed: true, stage, steps: { connection: false, trust: "none", credential: false, tested: false }, ...over });
  const states = (stage: string) => readinessSteps(r(stage))!.map((s) => `${s.label}:${s.state}`);
  expect(states("registered")).toEqual(["Cadastrada:done", "Conexão aplicada:current", "Confirmação no Edge:pending", "Credencial aplicada:pending", "Testada:pending"]);
  expect(states("connection_applied")).toEqual(["Cadastrada:done", "Conexão aplicada:done", "Confirmação no Edge:current", "Credencial aplicada:pending", "Testada:pending"]);
  expect(states("awaiting_trust")).toEqual(["Cadastrada:done", "Conexão aplicada:done", "Aguardando confirmação no Edge:current", "Credencial aplicada:pending", "Testada:pending"]);
  expect(states("trusted")).toEqual(["Cadastrada:done", "Conexão aplicada:done", "Confirmada no Edge:done", "Credencial aplicada:current", "Testada:pending"]);
  expect(states("credential_applied")).toEqual(["Cadastrada:done", "Conexão aplicada:done", "Confirmada no Edge:done", "Credencial aplicada:done", "Testada:current"]);
  expect(states("tested").every((x) => x.endsWith(":done"))).toBe(true);
  expect(readinessSteps(r("telnet_inventory"))).toBeNull();                     // Telnet não tem cadeia
  expect(stageText(r("telnet_inventory"))).toBe("Aguardando suporte a Telnet (só cadastro)");
  expect(readinessSteps({ managed: false, stage: "registered", steps: { connection: false, trust: "none", credential: false, tested: false } })).toBeNull();
  expect(stageText({ managed: false, stage: "registered", steps: { connection: false, trust: "none", credential: false, tested: false } })).toContain("Cadastro simples");
  expect(stageText(r("awaiting_trust"))).toBe("Aguardando confirmação no Edge");
});

// ---- selagem do kind olt_connection: o navegador (WebCrypto) sela, o "Edge" (Node crypto) abre com a AAD certa
function newEdgeKey() {
  const ecdh = createECDH("prime256v1");
  ecdh.generateKeys();
  const point = ecdh.getPublicKey();
  const digest = createHash("sha256").update(point).digest("hex");
  return { ecdh, pub: b64urlEncode(new Uint8Array(point)), keyId: digest.slice(0, 16) };
}
function openBlob(edge: ReturnType<typeof newEdgeKey>, blob: Uint8Array, aad: string): string {
  const b = Buffer.from(blob);
  const key = Buffer.from(hkdfSync("sha256", edge.ecdh.computeSecret(b.subarray(1, 66)), Buffer.alloc(0), Buffer.from(`fibercore-seal-v1|${edge.keyId}`), 32));
  const d = createDecipheriv("aes-256-gcm", key, b.subarray(66, 78));
  d.setAAD(Buffer.from(aad));
  d.setAuthTag(b.subarray(b.length - 16));
  return Buffer.concat([d.update(b.subarray(78, b.length - 16)), d.final()]).toString("utf8");
}

test("selagem do kind olt_connection: o Edge abre o texto do ADR com a AAD (kind incluído) e NÃO abre com outro kind", async () => {
  const edge = newEdgeKey();
  const r = connectionPlain({ id: OLT_ID, vendor: "huawei", connection: conn() }, "10.77.88.99");
  if ("problem" in r) throw new Error(r.problem);
  const input = { tenantId: "11111111-1111-4111-8111-111111111111", edgeId: "22222222-2222-4222-8222-222222222222", oltName: "OLT-CENTRO-01", deliveryId: "33333333-3333-4333-8333-333333333333", keyId: edge.keyId, expiresAtUnix: 1_900_000_000, edgePublicKey: edge.pub, plain: r.plain };
  const sealed = await sealOltSecret(input);
  expect(sealed.sealed.length).toBeLessThanOrEqual(2048);
  expect(sealed.sealed).not.toContain("10.77.88.99");                          // nem em claro nem em base64 do JSON
  expect(Buffer.from(b64urlDecode(sealed.sealed)).toString("latin1")).not.toContain("10.77.88.99");
  const aad = ["fibercore-seal-v1", input.tenantId, input.edgeId, "OLT-CENTRO-01", "olt_connection", input.deliveryId, edge.keyId, "1900000000"].join("\n");
  expect(sealed.aad).toBe(aad);
  expect(aadFor({ ...input, kind: "olt_connection" })).toBe(aad);
  expect(openBlob(edge, sealed.blob, aad)).toBe(plainJson(r.plain));
  expect(JSON.parse(openBlob(edge, sealed.blob, aad))).toMatchObject({ kind: "olt_connection", action: "set", address: "10.77.88.99", cloud_id: OLT_ID });
  expect(() => openBlob(edge, sealed.blob, aad.replace("olt_connection", "ssh_login"))).toThrow();            // o kind é autenticado
  expect(() => openBlob(edge, sealed.blob, aad.replace("OLT-CENTRO-01", "OLT-OUTRA"))).toThrow();
  const again = await sealOltSecret(input);                                                                   // efêmera e nonce novos a cada selagem
  expect(again.sealed).not.toBe(sealed.sealed);
  await expect(sealOltSecret({ ...input, plain: { ...r.plain, host_key_sha256: "SHA256:x" } as ConnectionPlain })).rejects.toThrow(/impressão digital/);   // falha fechada: nada é selado com dado inválido
  await expect(sealOltSecret({ ...input, plain: { ...r.plain, address: "127.0.0.1" } as ConnectionPlain })).rejects.toThrow();
});
