// Compiled Intelligence: tipos compartidos
// Submission @Agusting22 — Galo Workshop Challenge

/**
 * Conjunto cerrado de acciones que el sistema sabe ejecutar.
 * Cada `action_type` corresponde a una instrucción estructurada que se
 * transmite al ERP downstream de la empresa contratante. Galo no factura
 * directamente — solo orquesta la instrucción.
 *
 * `custom_instruction` es el escape hatch para el long tail: si una
 * observación no mapea a ningún tipo conocido, se preserva como texto
 * libre y se transmite tal cual al ERP / al operador.
 */
export type ActionType =
  | "split_invoice"           // dividir comprobante en N facturas con proporciones
  | "assign_razon_social"     // asignar a una de las razones sociales del cliente
  | "set_invoice_type"        // tipo A, B, C, etc.
  | "add_iva_line"            // sumar IVA como línea separada
  | "apply_discount"          // descuento puntual
  | "split_amount"            // dividir monto en partes
  | "custom_instruction";     // catch-all: texto libre para el operador / ERP

export type Action =
  | { type: "split_invoice"; parts: Array<{ ratio: number; invoice_type: "A" | "B" | "C" }> }
  | { type: "assign_razon_social"; cuit: string; reason?: string }
  | { type: "set_invoice_type"; invoice_type: "A" | "B" | "C" }
  | { type: "add_iva_line"; rate: number }
  | { type: "apply_discount"; pct: number; reason?: string }
  | { type: "split_amount"; parts: number[] }     // ej: [0.5, 0.5] o [0.3, 0.4, 0.3]
  | { type: "custom_instruction"; text: string };

export type Rule = {
  id: string;
  client_cuit: string | null;        // null = regla global
  trigger_text: string;              // texto original como lo escribió el cliente
  trigger_normalized: string;        // normalizado (lowercase, sin tildes, etc.)
  trigger_hash: string;              // sha1(trigger_normalized)
  trigger_embedding: number[] | null;
  action_type: ActionType;
  action_params: Record<string, unknown>;
  confidence: number;                // 0..1
  times_used: number;
  last_used_at: Date | null;
  source_interaction_id: string;
  active: boolean;
  created_at: Date;
};

export type ClientDNA = {
  cuit: string;
  display_name: string | null;
  quirks_digest: string;             // resumen NL, ~150 tokens
  quirks_digest_at: Date | null;
  rules_since_digest: number;
  razones_sociales: Array<{
    cuit: string;
    name: string;
    selection_rule?: { type: "amount_gte" | "amount_lt" | "default"; value?: number };
  }>;
  bank_patterns: string[];
  total_receipts: number;
  last_seen: Date | null;
  resolution_rate: number;
};

export type Receipt = {
  amount: number;
  cuit: string;                      // del cliente
  cbu: string;
  bank: string;
  observation: string;               // el campo problemático
  raw_image_url?: string;
};

export type ResolutionPath =
  | "no_observation"     // observación vacía o trivial, procesado normal
  | "exact"              // match en Nivel 1
  | "fuzzy"              // match en Nivel 2
  | "semantic"           // match en Nivel 3
  | "llm_dna"            // inferencia con quirks_digest
  | "operator";          // escalación humana

export type Resolution = {
  path: ResolutionPath;
  rule?: Rule;
  action: Action;
  cost_usd: number;
  latency_ms: number;
};
