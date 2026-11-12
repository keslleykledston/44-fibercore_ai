"""Centro de OLT (ADR-0046, D3/D4/D5): como a OLT é alcançada (protocolo, porta, transporte, impressão digital do host) e o estado de confiança local no Edge

`olts` ganha os campos de conexão (NÃO secretos: o endereço continua só mascarado na leitura; a impressão digital do host é pública) e o estado que o EDGE informa (`edge_trust_state`).
`olt_secret_deliveries.kind` aceita `olt_connection` (mesmo canal, selagem, assinatura, estados e retenção do ADR-0045).

Quem pode escrever o quê (decisão e justificativa):
* os campos de conexão são editáveis pela role da aplicação (GRANT de coluna INSERT/UPDATE só neles), como `mgmt_address` desde a 0048;
* `edge_trust_state` e `conn_applied_at` NÃO têm GRANT de coluna: a role da aplicação não consegue gravá-los por UPDATE nenhum. O ÚNICO escritor é a função SECURITY DEFINER estreita
  `app_olt_edge_report(olt, edge, evento)`, que só mexe na OLT DAQUELE Edge, do tenant da sessão (RLS forçada), exige protocolo `ssh` e o registro aplicado antes de aceitar `awaiting_local_trust`/`trusted`
  e devolve `ignored` (sem revelar nada) para qualquer outra OLT. Escolhi função em vez de GRANT de coluna porque o padrão do repo para o que só a rota do Edge pode tocar
  (`app_secret_delivery_blob`, `app_sweep_secret_deliveries`) já é função estreita, e porque a invariante (estado só avança com o registro aplicado) fica no banco e não em cada rota.
* o REBAIXAMENTO é automático e do banco: o gatilho `olts_connection_guard` zera `edge_trust_state` e `conn_applied_at` quando muda qualquer campo de conexão (endereço, porta, protocolo, transporte,
  porta SNMP, impressão digital, modo SSH, SSH legado), por qualquer rota (inclui a de usuário). Mudar para Telnet também zera.

Telnet é inventário sem credencial operacional (D3): um CHECK impede que uma OLT Telnet guarde impressão digital, modo SSH, SSH legado, confiança ou conexão aplicada.

Reversível. Revision ID: 0051  Revises: 0050
"""
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

USER_COLS = "mgmt_protocol, mgmt_port, mgmt_transport, snmp_port, host_key_sha256, ssh_mode, legacy_ssh"


def upgrade() -> None:
    cur_t = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"""
        ALTER TABLE olts
          ADD COLUMN mgmt_protocol text,
          ADD COLUMN mgmt_port integer,
          ADD COLUMN mgmt_transport text,
          ADD COLUMN snmp_port integer,
          ADD COLUMN host_key_sha256 text,
          ADD COLUMN ssh_mode text,
          ADD COLUMN legacy_ssh boolean NOT NULL DEFAULT false,
          ADD COLUMN edge_trust_state text NOT NULL DEFAULT 'none',
          ADD COLUMN conn_applied_at timestamptz,
          ADD CONSTRAINT olts_mgmt_protocol_values CHECK (mgmt_protocol IS NULL OR mgmt_protocol IN ('ssh', 'telnet')),
          ADD CONSTRAINT olts_mgmt_port_range CHECK (mgmt_port IS NULL OR mgmt_port BETWEEN 1 AND 65535),
          ADD CONSTRAINT olts_mgmt_transport_values CHECK (mgmt_transport IS NULL OR mgmt_transport IN ('cli', 'snmp')),
          ADD CONSTRAINT olts_snmp_port_range CHECK (snmp_port IS NULL OR snmp_port BETWEEN 1 AND 65535),
          ADD CONSTRAINT olts_host_key_shape CHECK (host_key_sha256 IS NULL OR host_key_sha256 ~ '^SHA256:[A-Za-z0-9+/]{{43}}$'),
          ADD CONSTRAINT olts_ssh_mode_values CHECK (ssh_mode IS NULL OR ssh_mode IN ('exec', 'shell')),
          ADD CONSTRAINT olts_edge_trust_values CHECK (edge_trust_state IN ('none', 'awaiting_local_trust', 'trusted')),
          -- a porta só existe com protocolo; impressão digital, modo SSH e SSH legado só existem para SSH (Telnet = inventário, nunca credencial operacional)
          ADD CONSTRAINT olts_mgmt_port_needs_protocol CHECK (mgmt_port IS NULL OR mgmt_protocol IS NOT NULL),
          ADD CONSTRAINT olts_ssh_fields_need_ssh CHECK (COALESCE(mgmt_protocol = 'ssh', false) OR (host_key_sha256 IS NULL AND ssh_mode IS NULL AND NOT legacy_ssh)),
          ADD CONSTRAINT olts_telnet_never_trusted CHECK (COALESCE(mgmt_protocol = 'ssh', false) OR (edge_trust_state = 'none' AND conn_applied_at IS NULL)),
          ADD CONSTRAINT olts_trust_needs_applied CHECK (edge_trust_state = 'none' OR conn_applied_at IS NOT NULL),
          ADD CONSTRAINT olts_snmp_transport_needs_v2c CHECK (mgmt_transport IS DISTINCT FROM 'snmp' OR COALESCE(snmp_version = 'v2c', false));
        GRANT INSERT ({USER_COLS}) ON olts TO fibercore_app;
        GRANT UPDATE ({USER_COLS}) ON olts TO fibercore_app;
        -- NO grant on edge_trust_state / conn_applied_at: only app_olt_edge_report (below) writes them, and olts_connection_guard demotes them

        CREATE FUNCTION olts_connection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (NEW.mgmt_address, NEW.mgmt_protocol, NEW.mgmt_port, NEW.mgmt_transport, NEW.snmp_port, NEW.host_key_sha256, NEW.ssh_mode, NEW.legacy_ssh)
             IS DISTINCT FROM (OLD.mgmt_address, OLD.mgmt_protocol, OLD.mgmt_port, OLD.mgmt_transport, OLD.snmp_port, OLD.host_key_sha256, OLD.ssh_mode, OLD.legacy_ssh) THEN
            NEW.edge_trust_state := 'none';   -- any change of HOW the OLT is reached voids what the Edge confirmed and what it applied: a new delivery and a new local confirmation are needed
            NEW.conn_applied_at := NULL;
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER olts_connection_guard BEFORE UPDATE ON olts FOR EACH ROW EXECUTE FUNCTION olts_connection_guard();

        -- the ONLY writer of edge_trust_state / conn_applied_at: the Edge's own report about ITS OLT of the session tenant. Returns 'changed', 'same' or 'ignored' (not this Edge's OLT, not ssh, or
        -- not applicable yet): the caller never learns more than that
        CREATE FUNCTION app_olt_edge_report(p_olt uuid, p_edge uuid, p_event text) RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        DECLARE n integer;
        BEGIN
          IF p_event NOT IN ('connection_applied', 'awaiting_local_trust', 'trusted', 'removed') THEN
            RAISE EXCEPTION 'app_olt_edge_report: unknown event';
          END IF;
          IF p_event = 'connection_applied' THEN
            UPDATE olts SET conn_applied_at = now() WHERE tenant_id = {cur_t} AND id = p_olt AND edge_id = p_edge AND mgmt_protocol = 'ssh';
            GET DIAGNOSTICS n = ROW_COUNT;
            RETURN CASE WHEN n > 0 THEN 'changed' ELSE 'ignored' END;
          ELSIF p_event = 'removed' THEN
            UPDATE olts SET edge_trust_state = 'none', conn_applied_at = NULL
             WHERE tenant_id = {cur_t} AND id = p_olt AND edge_id = p_edge AND (edge_trust_state <> 'none' OR conn_applied_at IS NOT NULL);
            GET DIAGNOSTICS n = ROW_COUNT;
            IF n > 0 THEN RETURN 'changed'; END IF;
          ELSE
            UPDATE olts SET edge_trust_state = p_event
             WHERE tenant_id = {cur_t} AND id = p_olt AND edge_id = p_edge AND mgmt_protocol = 'ssh' AND conn_applied_at IS NOT NULL AND edge_trust_state <> p_event;
            GET DIAGNOSTICS n = ROW_COUNT;
            IF n > 0 THEN RETURN 'changed'; END IF;
            RETURN CASE WHEN EXISTS (SELECT 1 FROM olts WHERE tenant_id = {cur_t} AND id = p_olt AND edge_id = p_edge AND mgmt_protocol = 'ssh' AND conn_applied_at IS NOT NULL AND edge_trust_state = p_event)
                        THEN 'same' ELSE 'ignored' END;
          END IF;
          RETURN CASE WHEN EXISTS (SELECT 1 FROM olts WHERE tenant_id = {cur_t} AND id = p_olt AND edge_id = p_edge) THEN 'same' ELSE 'ignored' END;
        END $$;
        REVOKE ALL ON FUNCTION app_olt_edge_report(uuid, uuid, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION app_olt_edge_report(uuid, uuid, text) TO fibercore_app;

        -- the delivery channel of ADR-0045 now also carries the OLT's connection
        ALTER TABLE olt_secret_deliveries DROP CONSTRAINT olt_secret_deliveries_kind_check;
        ALTER TABLE olt_secret_deliveries ADD CONSTRAINT olt_secret_deliveries_kind_check CHECK (kind IN ('ssh_login', 'snmp_community', 'olt_connection'));
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM olt_secret_deliveries WHERE kind = 'olt_connection';   -- transient table (blobs live <= 1 h): nothing durable is lost
        ALTER TABLE olt_secret_deliveries DROP CONSTRAINT olt_secret_deliveries_kind_check;
        ALTER TABLE olt_secret_deliveries ADD CONSTRAINT olt_secret_deliveries_kind_check CHECK (kind IN ('ssh_login', 'snmp_community'));
        DROP FUNCTION IF EXISTS app_olt_edge_report(uuid, uuid, text);
        DROP TRIGGER IF EXISTS olts_connection_guard ON olts;
        DROP FUNCTION IF EXISTS olts_connection_guard();
        REVOKE INSERT ({USER_COLS}) ON olts FROM fibercore_app;
        REVOKE UPDATE ({USER_COLS}) ON olts FROM fibercore_app;
        ALTER TABLE olts
          DROP CONSTRAINT IF EXISTS olts_snmp_transport_needs_v2c, DROP CONSTRAINT IF EXISTS olts_trust_needs_applied, DROP CONSTRAINT IF EXISTS olts_telnet_never_trusted,
          DROP CONSTRAINT IF EXISTS olts_ssh_fields_need_ssh, DROP CONSTRAINT IF EXISTS olts_mgmt_port_needs_protocol, DROP CONSTRAINT IF EXISTS olts_edge_trust_values,
          DROP CONSTRAINT IF EXISTS olts_ssh_mode_values, DROP CONSTRAINT IF EXISTS olts_host_key_shape, DROP CONSTRAINT IF EXISTS olts_snmp_port_range,
          DROP CONSTRAINT IF EXISTS olts_mgmt_transport_values, DROP CONSTRAINT IF EXISTS olts_mgmt_port_range, DROP CONSTRAINT IF EXISTS olts_mgmt_protocol_values,
          DROP COLUMN IF EXISTS conn_applied_at, DROP COLUMN IF EXISTS edge_trust_state, DROP COLUMN IF EXISTS legacy_ssh, DROP COLUMN IF EXISTS ssh_mode,
          DROP COLUMN IF EXISTS host_key_sha256, DROP COLUMN IF EXISTS snmp_port, DROP COLUMN IF EXISTS mgmt_transport, DROP COLUMN IF EXISTS mgmt_port, DROP COLUMN IF EXISTS mgmt_protocol;
        """
    )
