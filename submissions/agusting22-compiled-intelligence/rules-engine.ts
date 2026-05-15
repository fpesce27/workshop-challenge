// Compiled Intelligence: Rules Engine
// Submission @Agusting22 — Galo Workshop Challenge
//
// Cascada de 3 niveles para resolver una observación a una acción:
//   Nivel 1: exact match por hash       (<1ms, $0)
//   Nivel 2: fuzzy match por trigramas  (<5ms, $0)
//   Nivel 3: semantic match por embedding (~100ms, ~$0.0001)
//
// En cada nivel, las reglas per-client tienen prioridad sobre las globales.
// El motor se corta en el primer nivel que matchea.

import { createHash } from "node:crypto";
import type { Pool } from "pg";
import type { Rule, Resolution } from "./types";

type Embedder = (text: string) => Promise<number[]>;

/**
 * Normaliza una observación para matching consistente:
 *   - lowercase
 *   - sin tildes (NFD + strip de combining marks)
 *   - sin puntuación redundante
 *   - colapsa whitespace
 *
 * Cubre el caso "el cliente escribió lo mismo con typos triviales".
 * Las variaciones más grandes las captura el nivel fuzzy o semantic.
 */
export function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")   // strip combining marks (tildes)
    .toLowerCase()
    .replace(/[.,;:!?¡¿]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function hashTrigger(normalized: string): string {
  return createHash("sha1").update(normalized).digest("hex");
}

/**
 * Decide si una observación requiere interpretación o si es texto plano
 * (ej: "pago factura 00234") que puede procesarse sin tocar la memoria.
 *
 * Heurística conservadora: si hay verbos imperativos, sustantivos de
 * dominio, o patrones numéricos ambiguos, requiere interpretación.
 */
export function requiresInterpretation(observation: string): boolean {
  if (!observation || observation.trim().length < 3) return false;
  const text = normalize(observation);

  // Texto plano: solo números, espacios, y referencias a facturas
  if (/^[\d\s\-/#.\sn°ºfactura]+$/i.test(text)) return false;

  const triggers = [
    /\b(armar|hacer|dividir|partir|sumar|restar|separar|aplicar)\b/,
    /\b(factura|razon|raz[oó]n social|iva|comprobante|n[oó]ta)\b/,
    /\b\d+\s*\/\s*\d+\b/,   // patrones tipo 50/50, 30/70, 60/40
  ];
  return triggers.some((re) => re.test(text));
}

/**
 * El Rules Engine. Construido sobre las funciones SQL definidas en schema.sql
 * (`match_exact`, `match_fuzzy`, `match_semantic`).
 */
export class RulesEngine {
  constructor(
    private readonly db: Pool,
    private readonly embed: Embedder,
  ) {}

  /**
   * Resuelve una observación. Devuelve la primera regla que matchea
   * en la cascada, o null si nada matchea.
   *
   * El caller usa el `path` devuelto para saber qué pasó:
   *   - 'exact' | 'fuzzy' | 'semantic' → hubo regla
   *   - null → escalar a LLM con DNA o al operador
   */
  async match(cuit: string, observation: string): Promise<{ rule: Rule; path: "exact" | "fuzzy" | "semantic" } | null> {
    const normalized = normalize(observation);
    const hash = hashTrigger(normalized);

    // Nivel 1: exact
    const exact = await this.queryFn("match_exact", [cuit, hash]);
    if (exact) {
      await this.recordUsage(exact.id);
      return { rule: exact, path: "exact" };
    }

    // Nivel 2: fuzzy
    const fuzzy = await this.queryFn("match_fuzzy", [cuit, normalized, 0.3]);
    if (fuzzy) {
      await this.recordUsage(fuzzy.id);
      return { rule: fuzzy, path: "fuzzy" };
    }

    // Nivel 3: semantic (paga el costo del embedding solo si los dos anteriores fallaron)
    const embedding = await this.embed(observation);
    const semantic = await this.queryFn("match_semantic", [cuit, toPgVector(embedding), 0.18]);
    if (semantic) {
      await this.recordUsage(semantic.id);
      return { rule: semantic, path: "semantic" };
    }

    return null;
  }

  private async queryFn(fn: string, args: unknown[]): Promise<Rule | null> {
    const placeholders = args.map((_, i) => `$${i + 1}`).join(", ");
    const { rows } = await this.db.query<Rule>(
      `SELECT * FROM ${fn}(${placeholders})`,
      args,
    );
    return rows[0] ?? null;
  }

  private async recordUsage(ruleId: string): Promise<void> {
    await this.db.query(
      `UPDATE rules SET times_used = times_used + 1, last_used_at = now() WHERE id = $1`,
      [ruleId],
    );
  }
}

function toPgVector(v: number[]): string {
  return `[${v.join(",")}]`;
}

// ----------------------------------------------------------------------
// Wiring para el flujo end-to-end. Una función de alto nivel que el agente
// llama al recibir un comprobante con observación ambigua.
// ----------------------------------------------------------------------

export async function resolveObservation(
  engine: RulesEngine,
  receipt: { cuit: string; observation: string },
): Promise<Resolution | null> {
  if (!requiresInterpretation(receipt.observation)) {
    return { path: "no_observation", action: { type: "custom_instruction", text: "" }, cost_usd: 0, latency_ms: 0 };
  }

  const t0 = performance.now();
  const match = await engine.match(receipt.cuit, receipt.observation);
  const latency = performance.now() - t0;

  if (!match) return null;

  return {
    path: match.path,
    rule: match.rule,
    action: { type: match.rule.action_type, ...match.rule.action_params } as Resolution["action"],
    cost_usd: match.path === "semantic" ? 0.0001 : 0,
    latency_ms: Math.round(latency),
  };
}
