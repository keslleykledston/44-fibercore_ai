import { expect, test } from "@playwright/test";
import { ACS_FLASH, countText, ERROR_TEXT, errorText, flashFor, HEALTH_TEXT, kindLabel, nameProblem, seenText } from "../src/lib/acs";

// Textos e regras da tela de ACS (ADR-0046 D2): funções puras, sem navegador nem API.
const API_CODES = ["unreachable", "timeout", "unauthorized", "unexpected_status", "bad_response", "too_large", "unknown"];   // app/core/acs.py ACS_ERROR_CODES

test("todo código de erro que a API aceita tem texto em português e um código desconhecido nunca aparece cru", () => {
  expect(Object.keys(ERROR_TEXT).sort()).toEqual([...API_CODES].sort());
  for (const c of API_CODES) expect(errorText(c)).toMatch(/[a-zç]/);
  expect(errorText("hunter2-novo-codigo")).toBe(ERROR_TEXT.unknown);
  expect(errorText(null)).toBeNull();
});

test("o estado nunca é só cor: cada um tem texto e símbolo próprios", () => {
  const all = Object.values(HEALTH_TEXT);
  expect(new Set(all.map((h) => h.label)).size).toBe(4);
  expect(new Set(all.map((h) => h.symbol)).size).toBe(4);
  expect(Object.keys(HEALTH_TEXT).sort()).toEqual(["error", "ok", "stale", "unknown"]);
});

test("visto há…: sem relato é 'ainda não visto', nunca um tempo inventado", () => {
  const now = Date.parse("2026-11-12T12:00:00Z");
  expect(seenText(null, now)).toBe("ainda não visto");
  expect(seenText("2026-11-12T11:59:30Z", now)).toBe("visto agora há pouco");
  expect(seenText("2026-11-12T11:30:00Z", now)).toBe("visto há 30 min");
  expect(seenText("2026-11-12T08:00:00Z", now)).toBe("visto há 4 h");
  expect(seenText("2026-11-08T12:00:00Z", now)).toBe("visto há 4 d");
  expect(seenText("2026-11-12T12:05:00Z", now)).toBe("visto agora há pouco");   // relógio adiantado: nunca negativo
});

test("dispositivos: sem leitura é traço, zero é um número válido", () => {
  expect(countText(null)).toBe("—");
  expect(countText(0)).toBe("0 dispositivos");
  expect(countText(1)).toBe("1 dispositivo");
  expect(countText(1234)).toContain("1");
});

test("a falha da API vira a mensagem certa e nenhuma carrega o que foi digitado", () => {
  expect(flashFor(409, "edge_already_has_active_acs")).toBe("outroativo");
  expect(flashFor(409, "acs_name_taken")).toBe("nome");
  expect(flashFor(403, "feature_disabled")).toBe("desligado");
  expect(flashFor(403, "forbidden")).toBe("permissao");
  expect(flashFor(404, "edge not found")).toBe("edge");
  expect(flashFor(404, "acs not found")).toBe("naoexiste");
  expect(flashFor(422, "settings_unknown_key")).toBe("invalido");
  expect(flashFor(500, undefined)).toBe("falha");
  for (const k of ["criado", "atualizado", "ativado", "desativado", "permissao", "nome", "outroativo", "invalido", "edge", "naoexiste", "desligado", "falha"]) expect(ACS_FLASH[k]).toBeTruthy();
  expect(ACS_FLASH.criado).toContain("nbi_cloud_id");
  expect(ACS_FLASH.criado).toContain("continuam só no Edge");
});

test("nome: 2 a 60 caracteres, sem repetir o texto na mensagem", () => {
  expect(nameProblem("a")).not.toBeNull();
  expect(nameProblem("  ab  ")).toBeNull();
  expect(nameProblem("x".repeat(61))).not.toBeNull();
  expect(nameProblem("x".repeat(61))).not.toContain("xxx");
  expect(kindLabel("genieacs")).toBe("GenieACS");
  expect(kindLabel("outro")).toBe("outro");
});
