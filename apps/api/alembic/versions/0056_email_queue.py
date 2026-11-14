"""Fila de e-mail transacional (ADR-0048, fatia C): `email_queue` e as três entradas do worker `mailer`. Sem alerta, sem marketing, sem dado de cliente final.

`email_queue (tenant_id, id, kind, to_address, subject, body, created_by, created_at, expires_at, send_after, attempts, sent_at, failed_at, last_error)`. A mensagem já nasce PRONTA (texto
fixo em PT-BR montado pela API): o worker só entrega. Um link de uso único mora em `body` **só até ser enviado** (ou até expirar): enviado, expirado ou desistido, `body` vira NULL; a linha
fica 30 dias só como registro (quem, quando, tipo, resultado), sem corpo.

* A aplicação (`fibercore_app`) só INSERE e LÊ (política por organização; sem UPDATE, sem DELETE). Quem a lê NÃO vê o corpo: `GRANT SELECT` por coluna, sem `body`.
* O worker (`fibercore_worker`) não tem grant na tabela: entra por 3 funções `SECURITY DEFINER` (EXECUTE só a ele), como o `job-sweeper` (0047/0050):
  `app_mail_claim(p_batch)` reserva linhas vencidas (lease de 2 min; devolve o corpo), `app_mail_finish(p_id, p_ok, p_error)` marca enviado (apaga o corpo) ou agenda nova tentativa
  (máx. 5; depois `failed_at` e corpo apagado), `app_mail_sweep()` encerra o que expirou sem envio (corpo apagado) e remove registros com mais de 30 dias.
* O dono só enxerga, pela política `mail_scan`, linhas ainda não terminadas ou antigas: nunca uma mensagem já enviada recente.
Reversível: remove as funções e a tabela. Revision ID: 0056  Revises: 0055
"""
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

KINDS = ("member_invite", "password_reset", "mfa_reset_notice", "organization_suspended", "organization_reactivated")
KINDS_SQL = ", ".join(f"'{k}'" for k in KINDS)

CLAIM = """
CREATE FUNCTION app_mail_claim(p_batch integer) RETURNS TABLE (id uuid, tenant_id uuid, to_address text, subject text, body text, attempts integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r record;
BEGIN
  IF p_batch IS NULL OR p_batch NOT BETWEEN 1 AND 50 THEN RAISE EXCEPTION 'batch_invalid'; END IF;
  FOR r IN SELECT q.id AS qid, q.tenant_id AS qt FROM email_queue q
            WHERE q.sent_at IS NULL AND q.failed_at IS NULL AND q.expires_at > now() AND q.send_after <= now() AND q.attempts < 5
            ORDER BY q.created_at LIMIT p_batch LOOP
    -- no row lock in the scan (a locking read would also be checked against the UPDATE policy, which needs the tenant); the UPDATE below re-tests the conditions under the tenant, so two
    -- workers racing for one row cannot both get it: the second sees `send_after` already in the future
    PERFORM set_config('app.tenant_id', r.qt::text, true);
    RETURN QUERY UPDATE email_queue u SET attempts = u.attempts + 1, send_after = now() + interval '2 minutes'
                  WHERE u.id = r.qid AND u.tenant_id = r.qt AND u.sent_at IS NULL AND u.failed_at IS NULL AND u.expires_at > now() AND u.send_after <= now() AND u.attempts < 5
                  RETURNING u.id, u.tenant_id, u.to_address, u.subject, u.body, u.attempts;
  END LOOP;
  PERFORM set_config('app.tenant_id', '', true);
END $$;
"""

FINISH = """
CREATE FUNCTION app_mail_finish(p_id uuid, p_ok boolean, p_error text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE t uuid; n integer; att integer;
BEGIN
  SELECT q.tenant_id INTO t FROM email_queue q WHERE q.id = p_id AND q.sent_at IS NULL AND q.failed_at IS NULL;
  IF NOT FOUND THEN RETURN false; END IF;
  PERFORM set_config('app.tenant_id', t::text, true);
  IF p_ok THEN
    UPDATE email_queue SET sent_at = now(), body = NULL, last_error = NULL WHERE id = p_id AND tenant_id = t;
  ELSE
    SELECT attempts INTO att FROM email_queue WHERE id = p_id AND tenant_id = t;
    IF att >= 5 THEN
      UPDATE email_queue SET failed_at = now(), body = NULL, last_error = left(regexp_replace(COALESCE(p_error, 'error'), '[^A-Za-z0-9_.-]', '', 'g'), 40) WHERE id = p_id AND tenant_id = t;
    ELSE
      UPDATE email_queue SET send_after = now() + (att * interval '2 minutes'), last_error = left(regexp_replace(COALESCE(p_error, 'error'), '[^A-Za-z0-9_.-]', '', 'g'), 40) WHERE id = p_id AND tenant_id = t;
    END IF;
  END IF;
  PERFORM set_config('app.tenant_id', '', true);
  RETURN true;
END $$;
"""

SWEEP = """
CREATE FUNCTION app_mail_sweep() RETURNS TABLE (expired integer, purged integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE r record; a integer := 0; b integer := 0; n integer;
BEGIN
  FOR r IN SELECT q.id AS qid, q.tenant_id AS qt, q.sent_at IS NULL AND q.failed_at IS NULL AS open FROM email_queue q
            WHERE (q.sent_at IS NULL AND q.failed_at IS NULL AND q.expires_at <= now()) OR q.created_at < now() - interval '30 days' LOOP
    PERFORM set_config('app.tenant_id', r.qt::text, true);
    IF r.open THEN
      UPDATE email_queue SET failed_at = now(), body = NULL, last_error = 'expired' WHERE id = r.qid AND tenant_id = r.qt;
      a := a + 1;
    ELSE
      DELETE FROM email_queue WHERE id = r.qid AND tenant_id = r.qt; b := b + 1;
    END IF;
  END LOOP;
  PERFORM set_config('app.tenant_id', '', true);
  expired := a; purged := b;
  RETURN NEXT;
END $$;
"""

FUNCS = ["app_mail_claim(integer)", "app_mail_finish(uuid, boolean, text)", "app_mail_sweep()"]


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        CREATE TABLE email_queue (
          tenant_id uuid NOT NULL REFERENCES tenants(id),
          id uuid NOT NULL DEFAULT gen_random_uuid(),
          kind text NOT NULL CHECK (kind IN ({KINDS_SQL})),
          to_address text NOT NULL CHECK (to_address = lower(btrim(to_address)) AND length(to_address) <= 254 AND to_address ~ '^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$'),
          subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 200 AND subject !~ '[[:cntrl:]]'),
          body text CHECK (body IS NULL OR length(body) <= 8000),
          created_by uuid REFERENCES users_global(id),
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          send_after timestamptz NOT NULL DEFAULT now(),
          attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
          sent_at timestamptz,
          failed_at timestamptz,
          last_error text CHECK (last_error IS NULL OR length(last_error) <= 40),
          PRIMARY KEY (tenant_id, id),
          CONSTRAINT mail_window CHECK (expires_at > created_at AND expires_at <= created_at + interval '24 hours'),
          CONSTRAINT mail_one_end CHECK (sent_at IS NULL OR failed_at IS NULL),
          CONSTRAINT mail_body_only_while_open CHECK (body IS NULL OR (sent_at IS NULL AND failed_at IS NULL))
        );
        CREATE INDEX email_queue_due_idx ON email_queue (created_at) WHERE sent_at IS NULL AND failed_at IS NULL;
        ALTER TABLE email_queue ENABLE ROW LEVEL SECURITY;
        ALTER TABLE email_queue FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON email_queue USING (tenant_id = {cur_t}) WITH CHECK (tenant_id = {cur_t});
        -- the application can queue and read the RECORD, never the body (a link at rest) and never change or delete a row
        GRANT SELECT (tenant_id, id, kind, to_address, subject, created_by, created_at, expires_at, send_after, attempts, sent_at, failed_at, last_error) ON email_queue TO fibercore_app;
        GRANT INSERT (tenant_id, id, kind, to_address, subject, body, created_by, expires_at) ON email_queue TO fibercore_app;
        DO $$ BEGIN
          EXECUTE format($p$CREATE POLICY mail_scan ON email_queue FOR SELECT TO %I
                              USING ((sent_at IS NULL AND failed_at IS NULL) OR created_at < now() - interval '30 days')$p$, current_user);
        END $$;
        """
    )
    op.execute(CLAIM)
    op.execute(FINISH)
    op.execute(SWEEP)
    op.execute("\n".join(f"REVOKE ALL ON FUNCTION {f} FROM PUBLIC;\nGRANT EXECUTE ON FUNCTION {f} TO fibercore_worker;" for f in FUNCS))


def downgrade() -> None:
    for f in FUNCS:
        op.execute(f"DROP FUNCTION IF EXISTS {f}")
    op.execute("DROP TABLE IF EXISTS email_queue")
