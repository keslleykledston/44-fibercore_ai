import { createHmac } from "node:crypto";
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const EMAIL = process.env.DEMO_EMAIL ?? "admin@demo.example.com";
export const PASSWORD = process.env.DEMO_PASSWORD ?? "demo-password-123";

export const REVIEWER_EMAIL = process.env.DEMO_REVIEWER_EMAIL ?? "revisor@demo.example.com";

export async function login(page: Page, email: string = EMAIL) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha").fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: "Visão Geral" })).toBeVisible();
}

export const API_URL = process.env.E2E_API_URL ?? "http://127.0.0.1:18420";

/** TOTP (RFC 6238, SHA-1, 6 dígitos, 30 s) para o teste de MFA. */
export function totp(secretB32: string, stepOffset = 0): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const ch of secretB32.replace(/=+$/, "").toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000) + stepOffset));
  const h = createHmac("sha1", key).update(counter).digest();
  const o = h[h.length - 1] & 0x0f;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

/** Confirma (idempotente) o vínculo ONU↔CPE de DEMOA0002 e devolve o id da ONU. A configuração do aparelho é o perfil SINTÉTICO do seed (rotulado como tal). */
export async function onuWithConfirmedCpe(request: APIRequestContext) {
  const tok = (await (await request.post(`${API_URL}/v1/auth/token`, { data: { email: EMAIL, password: PASSWORD } })).json()).access_token as string;
  const h = { Authorization: `Bearer ${tok}` };
  expect((await request.post(`${API_URL}/v1/onu-cpe-links/suggest`, { headers: h })).status()).toBe(201);
  const links = (await (await request.get(`${API_URL}/v1/onu-cpe-links?status=suggested&limit=200`, { headers: h })).json()) as { id: string; onu: { id: string; serial: string } }[];
  const mine = links.find((l) => l.onu.serial === "DEMOA0002");
  if (mine) expect((await request.post(`${API_URL}/v1/onu-cpe-links/${mine.id}/confirm`, { headers: h })).status()).toBe(200);
  const onus = (await (await request.get(`${API_URL}/v1/onus?serial=DEMOA0002`, { headers: h })).json()) as { id: string; serial: string }[];
  return onus.find((o) => o.serial === "DEMOA0002")!.id;
}
