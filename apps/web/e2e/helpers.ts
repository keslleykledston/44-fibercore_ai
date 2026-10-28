import { expect, type Page } from "@playwright/test";

export const EMAIL = process.env.DEMO_EMAIL ?? "admin@demo.example.com";
export const PASSWORD = process.env.DEMO_PASSWORD ?? "demo-password-123";

export async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(EMAIL);
  await page.getByLabel("Senha").fill(PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: "Visão Geral" })).toBeVisible();
}
