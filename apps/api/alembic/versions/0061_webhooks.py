"""Webhooks de saída por organização (ADR-0051 D2, fatia F2): `webhook_endpoints`, `webhook_deliveries` e as quatro entradas do worker `webhooks`.

* `webhook_endpoints`: URL https, segredo HMAC CIFRADO (Fernet, chave do ambiente; a aplicação nunca lê a coluna `secret_enc`), lista de eventos de um catálogo FECHADO
  (`incident.opened`, `incident.resolved`; `webhook.test` é só o teste manual), ativo, contagem de falhas seguidas (10 desligam o endpoint).
* `webhook_deliveries`: um registro por (endpoint, evento), com a CARGA já montada (só chaves de uma lista fixa, nunca dado de cliente final) e a trilha da entrega. A carga vive até ser enviada
  ou desistida/expirada (24 h); depois vira NULL. Registro sem carga fica 30 dias.
* O worker (`fibercore_worker`) não tem grant nas tabelas: entra por funções `SECURITY DEFINER` (EXECUTE só a ele): `app_webhook_fanout(p_batch)` lê os eventos novos do outbox (uma política
  `webhook_outbox_scan` do DONO, só dos tipos do catálogo) e cria as entregas dos endpoints ativos da organização do evento, com um cursor em `webhook_cursor` (só eventos com mais de 10 s: uma transação lenta que confirma depois não fica para trás do cursor); `app_webhook_claim(p_batch)`
  reserva (lease 2 min) e devolve o que é preciso para enviar; `app_webhook_finish(p_id, p_ok, p_status, p_error)` registra; `app_webhook_sweep()` expira e limpa.
Reversível: remove políticas, funções e tabelas. Revision ID: 0061  Revises: 0060
"""
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

EVENTS = ("incident.opened", "incident.resolved")                       # what an endpoint may subscribe to
EVENTS_SQL = ", ".join(f"'{e}'" for e in EVENTS)
PAYLOAD_KEYS = ("kind", "pon_path", "onus_observed", "onus_down", "los", "dying_gasp", "suspected_cause", "members")   # the ONLY keys of an event's data that leave the platform
KEYS_SQL = ", ".join(f"'{k}'" for k in PAYLOAD_KEYS)

FANOUT = f"""
CREATE FUNCTION app_webhook_fanout(p_batch integer) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE c record; e record; ep record; made integer := 0; lastc timestamptz; lasti uuid; data jsonb; body jsonb;
BEGIN
  IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 500 THEN RAISE EXCEPTION 'batch_invalid'; END IF;
  INSERT INTO webhook_cursor (id, last_created_at, last_id) VALUES (true, now(), '00000000-0000-0000-0000-000000000000') ON CONFLICT (id) DO NOTHING;   -- first run: only what happens from now on
  SELECT last_created_at, last_id INTO lastc, lasti FROM webhook_cursor WHERE id FOR UPDATE;
  FOR e IN SELECT o.id, o.tenant_id, o.aggregate_id, o.event_type, o.payload, o.created_at FROM events_outbox o
            WHERE o.event_type IN ({EVENTS_SQL}) AND o.created_at < now() - interval '10 seconds' AND (o.created_at, o.id) > (lastc, lasti) ORDER BY o.created_at, o.id LIMIT p_batch LOOP
    PERFORM set_config('app.tenant_id', e.tenant_id::text, true);
    data := COALESCE((SELECT jsonb_object_agg(k, v) FROM jsonb_each(COALESCE(e.payload, '{{}}'::jsonb)) AS x(k, v) WHERE k IN ({KEYS_SQL})), '{{}}'::jsonb) || jsonb_build_object('incident_id', e.aggregate_id);
    body := jsonb_build_object('id', e.id, 'type', e.event_type, 'occurred_at', e.created_at, 'organization_id', e.tenant_id, 'data', data);
    FOR ep IN SELECT w.id FROM webhook_endpoints w WHERE w.tenant_id = e.tenant_id AND w.active AND e.event_type = ANY(w.events) LOOP
      INSERT INTO webhook_deliveries (tenant_id, endpoint_id, event_id, event_type, payload, expires_at)
        VALUES (e.tenant_id, ep.id, e.id, e.event_type, body, now() + interval '24 hours') ON CONFLICT (endpoint_id, event_id) DO NOTHING;
      made := made + 1;
    END LOOP;
    lastc := e.created_at; lasti := e.id;
  END LOOP;
  UPDATE webhook_cursor SET last_created_at = lastc, last_id = lasti WHERE id;
  PERFORM set_config('app.tenant_id', '', true);
  RETURN made;
END $$;
"""

CLAIM = """
CREATE FUNCTION app_webhook_claim(p_batch integer) RETURNS TABLE (id uuid, tenant_id uuid, url text, secret_enc text, event_type text, payload jsonb, attempts integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r record;
BEGIN
  IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 50 THEN RAISE EXCEPTION 'batch_invalid'; END IF;
  FOR r IN SELECT d.id AS did, d.tenant_id AS dt FROM webhook_deliveries d
            WHERE d.sent_at IS NULL AND d.failed_at IS NULL AND d.expires_at > now() AND d.next_attempt_at <= now() AND d.attempts < 8 ORDER BY d.created_at LIMIT p_batch LOOP
    PERFORM set_config('app.tenant_id', r.dt::text, true);
    RETURN QUERY UPDATE webhook_deliveries u SET attempts = u.attempts + 1, next_attempt_at = now() + interval '2 minutes'
                  FROM webhook_endpoints w
                  WHERE u.id = r.did AND u.tenant_id = r.dt AND u.sent_at IS NULL AND u.failed_at IS NULL AND u.expires_at > now() AND u.next_attempt_at <= now() AND u.attempts < 8
                    AND w.tenant_id = u.tenant_id AND w.id = u.endpoint_id AND (w.active OR u.event_type = 'webhook.test')
                  RETURNING u.id, u.tenant_id, w.url, w.secret_enc, u.event_type, u.payload, u.attempts;
  END LOOP;
  PERFORM set_config('app.tenant_id', '', true);
END $$;
"""

FINISH = """
CREATE FUNCTION app_webhook_finish(p_id uuid, p_ok boolean, p_status integer, p_error text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE t uuid; ep uuid; att integer; err text; fails integer;
BEGIN
  SELECT d.tenant_id, d.endpoint_id INTO t, ep FROM webhook_deliveries d WHERE d.id = p_id AND d.sent_at IS NULL AND d.failed_at IS NULL;
  IF NOT FOUND THEN RETURN false; END IF;
  PERFORM set_config('app.tenant_id', t::text, true);
  err := left(regexp_replace(COALESCE(p_error, ''), '[^A-Za-z0-9_.-]', '', 'g'), 40);
  IF p_ok THEN
    UPDATE webhook_deliveries SET sent_at = now(), payload = NULL, last_status = p_status, last_error = NULL WHERE id = p_id AND tenant_id = t;
    UPDATE webhook_endpoints SET consecutive_failures = 0, last_success_at = now() WHERE id = ep AND tenant_id = t;
  ELSE
    SELECT attempts INTO att FROM webhook_deliveries WHERE id = p_id AND tenant_id = t;
    IF att >= 8 THEN
      UPDATE webhook_deliveries SET failed_at = now(), payload = NULL, last_status = p_status, last_error = NULLIF(err, '') WHERE id = p_id AND tenant_id = t;
    ELSE
      UPDATE webhook_deliveries SET next_attempt_at = now() + (power(2, att) * interval '1 minute'), last_status = p_status, last_error = NULLIF(err, '') WHERE id = p_id AND tenant_id = t;
    END IF;
    UPDATE webhook_endpoints SET consecutive_failures = consecutive_failures + 1, last_failure_at = now() WHERE id = ep AND tenant_id = t RETURNING consecutive_failures INTO fails;
    IF fails >= 10 THEN
      UPDATE webhook_endpoints SET active = false, disabled_at = now(), disabled_reason = 'too_many_failures' WHERE id = ep AND tenant_id = t AND active;
    END IF;
  END IF;
  PERFORM set_config('app.tenant_id', '', true);
  RETURN true;
END $$;
"""

SWEEP = """
CREATE FUNCTION app_webhook_sweep() RETURNS TABLE (expired integer, purged integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r record; a integer := 0; b integer := 0;
BEGIN
  FOR r IN SELECT d.id AS did, d.tenant_id AS dt, d.sent_at IS NULL AND d.failed_at IS NULL AS open FROM webhook_deliveries d
            WHERE (d.sent_at IS NULL AND d.failed_at IS NULL AND d.expires_at <= now()) OR d.created_at < now() - interval '30 days' LOOP
    PERFORM set_config('app.tenant_id', r.dt::text, true);
    IF r.open THEN
      UPDATE webhook_deliveries SET failed_at = now(), payload = NULL, last_error = 'expired' WHERE id = r.did AND tenant_id = r.dt; a := a + 1;
    ELSE
      DELETE FROM webhook_deliveries WHERE id = r.did AND tenant_id = r.dt; b := b + 1;
    END IF;
  END LOOP;
  PERFORM set_config('app.tenant_id', '', true);
  expired := a; purged := b;
  RETURN NEXT;
END $$;
"""

FUNCS = ["app_webhook_fanout(integer)", "app_webhook_claim(integer)", "app_webhook_finish(uuid, boolean, integer, text)", "app_webhook_sweep()"]


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE webhook_endpoints (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          name text NOT NULL CHECK (length(btrim(name)) BETWEEN 2 AND 60 AND name !~ '[[:cntrl:]]'),
          url text NOT NULL CHECK (length(url) <= 500 AND url ~ '^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{{1,5}})?(/[^[:space:][:cntrl:]]*)?$'),
          secret_enc text NOT NULL,
          events text[] NOT NULL CHECK (cardinality(events) BETWEEN 1 AND 5 AND events <@ ARRAY[{EVENTS_SQL}]::text[]),
          active boolean NOT NULL DEFAULT true,
          consecutive_failures integer NOT NULL DEFAULT 0,
          last_success_at timestamptz,
          last_failure_at timestamptz,
          disabled_at timestamptz,
          disabled_reason text CHECK (disabled_reason IS NULL OR length(disabled_reason) <= 40),
          created_by uuid NOT NULL REFERENCES users_global(id),
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, id)
        );
        ALTER TABLE webhook_endpoints ENABLE ROW LEVEL SECURITY;
        ALTER TABLE webhook_endpoints FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON webhook_endpoints USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        -- the application never reads `secret_enc`; it may change the shown fields and the secret (rotation) but not read it back
        GRANT SELECT (tenant_id, id, name, url, events, active, consecutive_failures, last_success_at, last_failure_at, disabled_at, disabled_reason, created_by, created_at) ON webhook_endpoints TO fibercore_app;
        GRANT INSERT (tenant_id, id, name, url, secret_enc, events, created_by) ON webhook_endpoints TO fibercore_app;
        GRANT UPDATE (name, events, active, secret_enc, consecutive_failures, disabled_at, disabled_reason) ON webhook_endpoints TO fibercore_app;
        GRANT DELETE ON webhook_endpoints TO fibercore_app;

        CREATE TABLE webhook_deliveries (
          tenant_id uuid NOT NULL,
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          endpoint_id uuid NOT NULL,
          event_id uuid NOT NULL,
          event_type text NOT NULL CHECK (event_type IN ({EVENTS_SQL}, 'webhook.test')),
          payload jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          next_attempt_at timestamptz NOT NULL DEFAULT now(),
          attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 8),
          sent_at timestamptz,
          failed_at timestamptz,
          last_status integer,
          last_error text CHECK (last_error IS NULL OR length(last_error) <= 40),
          PRIMARY KEY (tenant_id, id),
          UNIQUE (endpoint_id, event_id),
          FOREIGN KEY (tenant_id, endpoint_id) REFERENCES webhook_endpoints (tenant_id, id) ON DELETE CASCADE,
          CONSTRAINT webhook_one_end CHECK (sent_at IS NULL OR failed_at IS NULL),
          CONSTRAINT webhook_payload_only_while_open CHECK (payload IS NULL OR (sent_at IS NULL AND failed_at IS NULL))
        );
        CREATE INDEX webhook_deliveries_due_idx ON webhook_deliveries (created_at) WHERE sent_at IS NULL AND failed_at IS NULL;
        ALTER TABLE webhook_deliveries ENABLE ROW LEVEL SECURITY;
        ALTER TABLE webhook_deliveries FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON webhook_deliveries USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        GRANT SELECT (tenant_id, id, endpoint_id, event_id, event_type, created_at, expires_at, next_attempt_at, attempts, sent_at, failed_at, last_status, last_error) ON webhook_deliveries TO fibercore_app;
        GRANT INSERT (tenant_id, id, endpoint_id, event_id, event_type, payload, expires_at) ON webhook_deliveries TO fibercore_app;

        CREATE TABLE webhook_cursor (id boolean PRIMARY KEY DEFAULT true CHECK (id), last_created_at timestamptz NOT NULL, last_id uuid NOT NULL);
        REVOKE ALL ON webhook_cursor FROM PUBLIC;

        -- the owner (the functions) sees: the new events of the catalog's types, the delivery rows still open or old, the active endpoints; nothing else of any organization
        DO $$ BEGIN
          EXECUTE format($p$CREATE POLICY webhook_outbox_scan ON events_outbox FOR SELECT TO %I USING (event_type IN ({EVENTS_SQL}))$p$, current_user);
          EXECUTE format($p$CREATE POLICY webhook_delivery_scan ON webhook_deliveries FOR SELECT TO %I USING ((sent_at IS NULL AND failed_at IS NULL) OR created_at < now() - interval '30 days')$p$, current_user);
          EXECUTE format($p$CREATE POLICY webhook_endpoint_scan ON webhook_endpoints FOR SELECT TO %I USING (true)$p$, current_user);
        END $$;
        """
    )
    for sql in (FANOUT, CLAIM, FINISH, SWEEP):
        op.execute(sql)
    op.execute("\n".join(f"REVOKE ALL ON FUNCTION {f} FROM PUBLIC;\nGRANT EXECUTE ON FUNCTION {f} TO fibercore_worker;" for f in FUNCS))


def downgrade() -> None:
    for f in FUNCS:
        op.execute(f"DROP FUNCTION IF EXISTS {f}")
    op.execute("DROP POLICY IF EXISTS webhook_outbox_scan ON events_outbox")
    op.execute("DROP TABLE IF EXISTS webhook_cursor, webhook_deliveries, webhook_endpoints")
