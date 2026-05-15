// Compiled Intelligence: Learning Pipeline
// Submission @Agusting22 — Galo Workshop Challenge
//
// Transforma una respuesta humana ("hacele 60/40 factura A y B") en una
// regla compilada lista para ejecutarse en el Rules Engine. Corre asíncrono,
// fuera del path crítico del comprobante.
//
// Seis pasos:
//   1. Clasificar scope (per-client | global)
//   2. Extraer regla (acción + params en JSON estructurado)
//   3. Compilar (normalizar trigger, hash, embedding)
//   4. Verificar conflictos
//   5. Persistir
//   6. Actualizar Client DNA (recompilar digest si ≥3 reglas nuevas)

import type { Pool } from "pg";
import type Anthropic from "@anthropic-ai/sdk";
import { hashTrigger, normalize } from "./rules-engine";
import type { Action, ActionType, ClientDNA, Rule } from "./types";

type Embedder = (text: string) => Promise<number[]>;

type CompilationInput = {
  client_cuit: string;
  observation: string;             // lo que escribió el cliente
  operator_reply: string;          // lo que respondió el operador
  source_interaction_id: string;
};

type CompiledRule = {
  scope: "per_client" | "global";
  action_type: ActionType;
  action_params: Record<string, unknown>;
};

export class LearningPipeline {
  constructor(
    private readonly db: Pool,
    private readonly llm: Anthropic,
    private readonly embed: Embedder,
  ) {}

  async compile(input: CompilationInput): Promise<{ ruleId: string | null; status: "created" | "merged" | "conflict" }> {
    // 1. Clasificar scope
    const scope = await this.classifyScope(input);

    // 2. Extraer la regla del lenguaje natural
    const extracted = await this.extractRule(input.observation, input.operator_reply);

    // 3. Compilar: normalizar, hashear, embedear
    const normalized = normalize(input.observation);
    const hash = hashTrigger(normalized);
    const embedding = await this.embed(input.observation);

    // 4. Verificar conflictos
    const existing = await this.findExisting(scope === "global" ? null : input.client_cuit, hash);

    if (existing) {
      const sameAction = isSameAction(existing, extracted);
      if (sameAction) {
        // Merge: incrementar times_used, no crear regla duplicada.
        await this.db.query(
          `UPDATE rules SET times_used = times_used + 1 WHERE id = $1`,
          [existing.id],
        );
        return { ruleId: existing.id, status: "merged" };
      } else {
        // Conflicto real: marcar para revisión humana, no auto-resolver.
        await this.db.query(
          `INSERT INTO conflicts (existing_rule_id, attempted_rule, reason)
           VALUES ($1, $2, $3)`,
          [
            existing.id,
            JSON.stringify({ scope, ...extracted, source_interaction_id: input.source_interaction_id }),
            "Same trigger, different action",
          ],
        );
        return { ruleId: null, status: "conflict" };
      }
    }

    // 5. Persistir
    const { rows } = await this.db.query<{ id: string }>(
      `INSERT INTO rules (
         client_cuit, trigger_text, trigger_normalized, trigger_hash, trigger_embedding,
         action_type, action_params, confidence, source_interaction_id
       )
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       RETURNING id`,
      [
        scope === "global" ? null : input.client_cuit,
        input.observation,
        normalized,
        hash,
        toPgVector(embedding),
        extracted.action_type,
        JSON.stringify(extracted.action_params),
        0.85,                          // confidence inicial para respuesta directa del operador
        input.source_interaction_id,
      ],
    );

    // 6. Actualizar Client DNA
    if (scope === "per_client") {
      await this.bumpClientDNA(input.client_cuit);
    }

    return { ruleId: rows[0].id, status: "created" };
  }

  /**
   * Paso 1: ¿per-client o global?
   *
   * Heurísticas primero (gratis). Si no son concluyentes, una llamada a Haiku.
   * Default conservador: per-client. El peor caso de equivocarse es
   * redundancia (compilar varias veces), no error (aplicar mal a otro cliente).
   */
  private async classifyScope(input: CompilationInput): Promise<"per_client" | "global"> {
    const reply = input.operator_reply.toLowerCase();

    // Heurística → per-client
    if (/este cliente|para este|él siempre|ella siempre|para [a-z\s]+ siempre/.test(reply)) {
      return "per_client";
    }
    // Heurística → global
    if (/en general|siempre que|para todos|cualquiera que|todos los clientes/.test(reply)) {
      return "global";
    }

    // No concluyente: preguntar a Haiku con prompt binario
    const result = await this.llm.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 10,
      messages: [{
        role: "user",
        content: `Una observación del cliente "${input.client_cuit}" dice: "${input.observation}"
El operador respondió: "${input.operator_reply}"

¿La respuesta del operador aplica solo a este cliente, o es un concepto general que podría aplicar a varios clientes?
Respondé exactamente una palabra: "per_client" o "global". Si tenés dudas, respondé "per_client".`,
      }],
    });
    const text = textOf(result).trim().toLowerCase();
    return text === "global" ? "global" : "per_client";
  }

  /**
   * Paso 2: extraer la acción estructurada del lenguaje natural.
   *
   * Haiku devuelve JSON con action_type del conjunto cerrado + params.
   * Si nada matchea, fallback a custom_instruction con el texto del operador.
   */
  private async extractRule(observation: string, reply: string): Promise<CompiledRule> {
    const result = await this.llm.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 200,
      messages: [{
        role: "user",
        content: `Extraé la instrucción estructurada de esta interacción:

Observación del cliente: "${observation}"
Respuesta del operador: "${reply}"

Devolvé JSON exacto con este schema:
{
  "action_type": "split_invoice" | "assign_razon_social" | "set_invoice_type" | "add_iva_line" | "apply_discount" | "split_amount" | "custom_instruction",
  "action_params": { ... }
}

Ejemplos:
- "factura A y B en 60/40" → {"action_type":"split_invoice","action_params":{"parts":[{"ratio":0.6,"invoice_type":"A"},{"ratio":0.4,"invoice_type":"B"}]}}
- "asignar a ABC SRL" → {"action_type":"assign_razon_social","action_params":{"name":"ABC SRL"}}
- "sumar IVA aparte 21%" → {"action_type":"add_iva_line","action_params":{"rate":0.21}}

Si la instrucción no encaja en ningún action_type del schema, usá "custom_instruction" con {"text": "..."}.
Devolvé SOLO el JSON, sin texto adicional.`,
      }],
    });

    try {
      const parsed = JSON.parse(textOf(result));
      const scope: CompiledRule = { scope: "per_client", action_type: parsed.action_type, action_params: parsed.action_params };
      return scope;
    } catch {
      // Fallback: si el LLM devolvió algo no parseable, preservar como custom_instruction
      return {
        scope: "per_client",
        action_type: "custom_instruction",
        action_params: { text: reply },
      };
    }
  }

  private async findExisting(cuit: string | null, hash: string): Promise<Rule | null> {
    const { rows } = await this.db.query<Rule>(
      `SELECT * FROM rules
       WHERE active = true
         AND trigger_hash = $2
         AND client_cuit IS NOT DISTINCT FROM $1
       LIMIT 1`,
      [cuit, hash],
    );
    return rows[0] ?? null;
  }

  private async bumpClientDNA(cuit: string): Promise<void> {
    const { rows } = await this.db.query<{ rules_since_digest: number }>(
      `UPDATE client_dna
       SET rules_since_digest = rules_since_digest + 1
       WHERE cuit = $1
       RETURNING rules_since_digest`,
      [cuit],
    );

    // Recompilar quirks_digest si acumuló ≥3 reglas nuevas.
    if (rows[0]?.rules_since_digest >= 3) {
      await this.recompileDigest(cuit);
    }
  }

  /**
   * Recompila el quirks_digest del cliente: resume todas las reglas activas
   * en un párrafo corto (~150 tokens). Una llamada a Haiku, ~$0.001.
   */
  private async recompileDigest(cuit: string): Promise<void> {
    const { rows: rules } = await this.db.query<{
      trigger_text: string; action_type: string; action_params: unknown;
    }>(
      `SELECT trigger_text, action_type, action_params
       FROM rules WHERE client_cuit = $1 AND active = true
       ORDER BY times_used DESC LIMIT 30`,
      [cuit],
    );

    if (rules.length === 0) return;

    const result = await this.llm.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 200,
      messages: [{
        role: "user",
        content: `Resumí en un párrafo corto (máximo 150 tokens, español neutro, presente indicativo) los hábitos de facturación de un cliente. Reglas activas:

${rules.map((r) => `- Cuando dice "${r.trigger_text}" → ${r.action_type}(${JSON.stringify(r.action_params)})`).join("\n")}

Devolvé solo el resumen, sin preámbulos.`,
      }],
    });

    await this.db.query(
      `UPDATE client_dna
       SET quirks_digest = $2, quirks_digest_at = now(), rules_since_digest = 0
       WHERE cuit = $1`,
      [cuit, textOf(result).trim()],
    );
  }
}

// ----------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------

function isSameAction(rule: Rule, compiled: CompiledRule): boolean {
  if (rule.action_type !== compiled.action_type) return false;
  return JSON.stringify(rule.action_params) === JSON.stringify(compiled.action_params);
}

function textOf(result: Anthropic.Messages.Message): string {
  const block = result.content[0];
  return block.type === "text" ? block.text : "";
}

function toPgVector(v: number[]): string {
  return `[${v.join(",")}]`;
}
