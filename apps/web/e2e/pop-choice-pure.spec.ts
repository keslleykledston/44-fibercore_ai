import { expect, test } from "@playwright/test";
import { popChoice } from "../src/lib/fleet";

// Regras do campo Site/POP do cadastro de OLT (funções puras: sem navegador nem API).
const pops = [{ id: "1", name: "Centro" }, { id: "2", name: "Km 06" }, { id: "3", name: "São Sebastião" }];

test("nome igual a um site existente (sem diferenciar maiúsculas e espaços) escolhe o site e não oferece criar", () => {
  const c = popChoice("  CENTRO ", pops);
  expect(c).toMatchObject({ id: "1", create: false, typed: "CENTRO" });
  expect(popChoice("são  sebastião", pops)).toMatchObject({ id: "3", create: false });
});
test("nome que não existe oferece criar, com busca parcial nas opções", () => {
  const c = popChoice("Km", pops);
  expect(c.id).toBeNull();
  expect(c.create).toBe(true);
  expect(c.matches.map((m) => m.id)).toEqual(["2"]);
  expect(popChoice("Bairro Novo", pops)).toMatchObject({ id: null, create: true, matches: [] });
});
test("vazio ou com 1 caractere não oferece criar; vazio lista tudo", () => {
  expect(popChoice("", pops)).toMatchObject({ id: null, create: false, typed: "" });
  expect(popChoice("", pops).matches).toHaveLength(3);
  expect(popChoice("x", pops).create).toBe(false);
});
