-- Compiled Intelligence: schema Postgres
-- Submission @Agusting22 — Galo Workshop Challenge
--
-- Requiere Postgres 15+ con extensiones pg_trgm y pgvector.
-- Probado contra Supabase (Postgres 15 + pgvector preinstalado).

------------------------------------------------------------
-- Extensiones
------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- fuzzy match por trigramas
CREATE EXTENSION IF NOT EXISTS vector;        -- pgvector para embeddings
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- gen_random_uuid

------------------------------------------------------------
-- Tabla: client_dna
-- Perfil compacto por cliente. NO crece — es una foto compilada.
------------------------------------------------------------

CREATE TABLE client_dna (
  cuit              text PRIMARY KEY,
  display_name      text,
  quirks_digest     text          DEFAULT '',          -- resumen NL de reglas activas, max ~150 tokens
  quirks_digest_at  timestamptz,                       -- última recompilación
  rules_since_digest int          DEFAULT 0,           -- contador para trigger de recompilación
  razones_sociales  jsonb         DEFAULT '[]'::jsonb, -- [{cuit, name, selection_rule}, ...]
  bank_patterns     jsonb         DEFAULT '[]'::jsonb, -- bancos habituales
  total_receipts    int           DEFAULT 0,
  last_seen         timestamptz,
  resolution_rate   numeric(5,4)  DEFAULT 0,           -- % resuelto sin escalación humana
  created_at        timestamptz   DEFAULT now()
);

CREATE INDEX client_dna_last_seen_idx ON client_dna(last_seen DESC);

------------------------------------------------------------
-- Tabla: interactions
-- Historial de cada decisión: comprobante → acción. Trazabilidad.
------------------------------------------------------------

CREATE TABLE interactions (
  id              uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  client_cuit     text          REFERENCES client_dna(cuit),
  observation     text          NOT NULL,
  resolution_path text          NOT NULL,        -- 'exact'|'fuzzy'|'semantic'|'llm_dna'|'operator'
  matched_rule_id uuid,                          -- nullable, FK a rules
  action          jsonb         NOT NULL,
  operator_reply  text,                          -- si hubo escalación
  cost_usd        numeric(10,6) DEFAULT 0,
  latency_ms      int,
  created_at      timestamptz   DEFAULT now()
);

CREATE INDEX interactions_client_idx ON interactions(client_cuit, created_at DESC);
CREATE INDEX interactions_path_idx   ON interactions(resolution_path);

------------------------------------------------------------
-- Tabla: rules
-- Reglas compiladas. El corazón del sistema.
------------------------------------------------------------

CREATE TABLE rules (
  id                     uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  client_cuit            text          REFERENCES client_dna(cuit),  -- NULL = global
  trigger_text           text          NOT NULL,                     -- original
  trigger_normalized     text          NOT NULL,                     -- lowercase, sin tildes, sin puntuación redundante
  trigger_hash           text          NOT NULL,                     -- sha1(trigger_normalized)
  trigger_embedding      vector(1536),                               -- text-embedding-3-small
  action_type            text          NOT NULL,                     -- 'split_invoice'|'assign_razon_social'|'custom_instruction'|...
  action_params          jsonb         NOT NULL DEFAULT '{}',
  confidence             numeric(4,3)  NOT NULL DEFAULT 0.85,
  times_used             int           NOT NULL DEFAULT 0,
  last_used_at           timestamptz,
  source_interaction_id  uuid          REFERENCES interactions(id),  -- de qué interacción salió
  active                 boolean       NOT NULL DEFAULT true,
  created_at             timestamptz   DEFAULT now(),
  deactivated_at         timestamptz,

  -- Una regla por (cuit, hash). NULL en cuit = global, una global por hash.
  -- Permite per-client + global del mismo trigger.
  -- Provenance del rule (diferencial §11): operator-given vs pre-compilada desde pedidos
  source                 text          NOT NULL DEFAULT 'operator_compiled',
    -- 'operator_compiled'      → respuesta directa del operador
    -- 'inferred_from_pedidos'  → minada del historial de pedidos (§11)
    -- 'candidate_global'       → promoción gradual desde per-client, todavía en cuarentena (§5)
    -- 'promoted_to_global'     → confirmada como global tras validaciones
  requires_first_validation boolean    NOT NULL DEFAULT false,                -- inferidas no actúan autónomas hasta validación humana
  scope_confidence       numeric(4,3)  NOT NULL DEFAULT 1.0,                  -- (F-05 fix) qué tan seguro estaba el clasificador per_client/global: 1.0 = heurística clara, 0.5 = Haiku borderline
  promotion_confirmations int          NOT NULL DEFAULT 0,                    -- contador de validaciones para sacar de candidate_global → promoted_to_global
  CONSTRAINT rules_source_check CHECK (source IN ('operator_compiled', 'inferred_from_pedidos', 'candidate_global', 'promoted_to_global')),
  CONSTRAINT rules_unique_per_scope UNIQUE NULLS NOT DISTINCT (client_cuit, trigger_hash)
);

-- Índice principal: exact match (B-tree).
-- Cubre filtro por hash y orden per-client first vía ORDER BY client_cuit NULLS LAST.
CREATE INDEX rules_hash_idx
  ON rules (trigger_hash)
  WHERE active = true;

-- Trigramas para fuzzy match.
CREATE INDEX rules_normalized_trgm_idx
  ON rules USING GIN (trigger_normalized gin_trgm_ops)
  WHERE active = true;

-- Embedding para semantic match. IVFFlat con lists ~= sqrt(rows_esperadas).
-- Para empezar con pocas filas: lists = 10. Re-tunear con REINDEX cuando crezca.
CREATE INDEX rules_embedding_idx
  ON rules USING ivfflat (trigger_embedding vector_cosine_ops)
  WITH (lists = 10)
  WHERE active = true;

-- Lookup por cliente para listar todas las reglas activas (recompilación de digest).
CREATE INDEX rules_client_idx
  ON rules (client_cuit, active)
  WHERE active = true;

------------------------------------------------------------
-- Tabla: conflicts
-- Reglas con misma trigger pero acción distinta. Marcadas para revisión humana.
------------------------------------------------------------

CREATE TABLE conflicts (
  id              uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  existing_rule_id uuid         REFERENCES rules(id),
  attempted_rule  jsonb         NOT NULL,    -- la regla nueva que entró en conflicto
  reason          text          NOT NULL,
  resolved        boolean       DEFAULT false,
  resolution      text,                       -- 'kept_existing'|'replaced'|'kept_both'
  created_at      timestamptz   DEFAULT now(),
  resolved_at     timestamptz
);

CREATE INDEX conflicts_unresolved_idx ON conflicts(resolved) WHERE resolved = false;

------------------------------------------------------------
-- Tabla: rule_negatives  (diferencial §12: aprendizaje negativo)
-- Contra-ejemplos: observaciones que matchearon una regla en el pasado
-- pero que el operador corrigió como falsos positivos. El matcher las usa
-- para rechazar over-matches en niveles fuzzy/semantic.
------------------------------------------------------------

CREATE TABLE rule_negatives (
  id                     uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_id                uuid          NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
  observation_text       text          NOT NULL,
  observation_normalized text          NOT NULL,
  observation_embedding  vector(1536),
  source_interaction_id  uuid          REFERENCES interactions(id),    -- de qué corrección salió
  created_at             timestamptz   DEFAULT now()
);

CREATE INDEX rule_negatives_rule_idx ON rule_negatives(rule_id);

------------------------------------------------------------
-- Tabla: inferred_patterns  (diferencial §11: pre-compilación predictiva)
-- Resultado del job de mining sobre el historial de pedidos.
-- Cada patrón detectado genera una rule con source='inferred_from_pedidos'.
-- Esta tabla mantiene la trazabilidad de qué pattern generó qué rule.
------------------------------------------------------------

CREATE TABLE inferred_patterns (
  id              uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
  client_cuit     text          NOT NULL REFERENCES client_dna(cuit),
  pattern_type    text          NOT NULL,    -- 'multi_category_orders' | 'bimodal_amount' | 'frequency' | 'industry_default'
  pattern_data    jsonb         NOT NULL,    -- estadísticas que respaldan el pattern (ej: {n_orders, avg_amount, threshold, ...})
  generated_rule_id uuid        REFERENCES rules(id) ON DELETE SET NULL,
  detected_at     timestamptz   DEFAULT now(),
  validated_at    timestamptz,                -- cuándo el operador confirmó (o rechazó) este pattern
  validation      text          CHECK (validation IN ('confirmed', 'rejected', 'pending')) DEFAULT 'pending'
);

CREATE INDEX inferred_patterns_client_idx ON inferred_patterns(client_cuit);
CREATE INDEX inferred_patterns_pending_idx ON inferred_patterns(validation) WHERE validation = 'pending';

------------------------------------------------------------
-- Funciones de matching
-- Encapsulan la cascada. La app llama match_exact, match_fuzzy, match_semantic en orden.
------------------------------------------------------------

-- Nivel 1: exact por hash. Per-client primero.
CREATE OR REPLACE FUNCTION match_exact(p_cuit text, p_hash text)
RETURNS SETOF rules AS $$
  SELECT *
  FROM rules
  WHERE active = true
    AND trigger_hash = p_hash
    AND (client_cuit = p_cuit OR client_cuit IS NULL)
  ORDER BY client_cuit NULLS LAST   -- per-client first
  LIMIT 1;
$$ LANGUAGE sql STABLE;

-- Nivel 2: fuzzy por trigramas. Umbral default 0.3.
CREATE OR REPLACE FUNCTION match_fuzzy(p_cuit text, p_normalized text, p_threshold numeric DEFAULT 0.3)
RETURNS SETOF rules AS $$
  SELECT *
  FROM rules
  WHERE active = true
    AND (client_cuit = p_cuit OR client_cuit IS NULL)
    AND similarity(trigger_normalized, p_normalized) >= p_threshold
  ORDER BY
    client_cuit NULLS LAST,
    similarity(trigger_normalized, p_normalized) DESC
  LIMIT 1;
$$ LANGUAGE sql STABLE;

-- Nivel 3: semantic por embedding. Umbral default 0.82 cosine sim => distance <= 0.18.
CREATE OR REPLACE FUNCTION match_semantic(p_cuit text, p_embedding vector(1536), p_max_distance numeric DEFAULT 0.18)
RETURNS SETOF rules AS $$
  SELECT *
  FROM rules
  WHERE active = true
    AND (client_cuit = p_cuit OR client_cuit IS NULL)
    AND trigger_embedding IS NOT NULL
    AND (trigger_embedding <=> p_embedding) <= p_max_distance
  ORDER BY
    client_cuit NULLS LAST,
    (trigger_embedding <=> p_embedding) ASC
  LIMIT 1;
$$ LANGUAGE sql STABLE;

------------------------------------------------------------
-- Diferencial §12: chequeo de negative examples antes de aceptar un match.
-- Devuelve TRUE si la observación es MÁS similar a algún negative example
-- de la regla que al trigger positivo. En ese caso, el caller rechaza el match.
------------------------------------------------------------

CREATE OR REPLACE FUNCTION rejected_by_negatives(
  p_rule_id uuid,
  p_observation_normalized text,
  p_observation_embedding vector(1536),
  p_positive_similarity numeric
) RETURNS boolean AS $$
  SELECT EXISTS (
    SELECT 1
    FROM rule_negatives
    WHERE rule_id = p_rule_id
      AND (
        -- Para fuzzy/trigrama, comparamos similitud textual.
        similarity(observation_normalized, p_observation_normalized) > p_positive_similarity
        OR
        -- Para semantic, comparamos distancia coseno (menor distancia = mayor similitud).
        (observation_embedding IS NOT NULL AND p_observation_embedding IS NOT NULL
         AND (1 - (observation_embedding <=> p_observation_embedding)) > p_positive_similarity)
      )
  );
$$ LANGUAGE sql STABLE;

------------------------------------------------------------
-- Vista: candidatos a promoción global
-- Reglas per-client con mismo trigger normalizado y acción que aparecen en 3+ clientes.
------------------------------------------------------------

CREATE VIEW global_promotion_candidates AS
SELECT
  trigger_normalized,
  action_type,
  action_params,
  COUNT(DISTINCT client_cuit) AS client_count,
  array_agg(DISTINCT client_cuit) AS clients
FROM rules
WHERE active = true
  AND client_cuit IS NOT NULL
GROUP BY trigger_normalized, action_type, action_params
HAVING COUNT(DISTINCT client_cuit) >= 3;
