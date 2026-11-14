"""E-mail transacional (ADR-0048, fatia C): modelos de texto FIXOS em PT-BR, fila (`email_queue`, migração 0056) e a entrega por SMTP.

Regras que valem aqui, uma vez:
* Só existe e-mail quando o ambiente da plataforma o configura (`SMTP_HOST`, `SMTP_FROM` e `PUBLIC_BASE_URL`). Sem isso `enabled()` é falso e a API segue como antes (o link aparece na tela).
* O texto é montado POR ESTE MÓDULO a partir de um modelo fixo; nunca de texto livre de uma organização. Nenhum dado de cliente final, nenhuma credencial de equipamento, nenhuma senha.
  O único segredo possível é o link de uso único de convite ou de troca de senha, que já seria mostrado na tela; ele vive no `body` da fila só até o envio (ver a migração 0056).
* Cabeçalhos são montados só com valores já validados (endereço do formato do banco, assunto fixo + nome da organização sem caracteres de controle): nada de quebra de linha vinda de fora.
* O endereço do link vem de `PUBLIC_BASE_URL` (configuração do operador do servidor), NUNCA de cabeçalho da requisição (`Host`/`Origin`): um cabeçalho forjado não consegue mandar o link
  de convite para outro domínio.
"""
from __future__ import annotations

import re
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.settings import Settings, get_settings

ADDRESS_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LINK_KINDS = {"member_invite", "password_reset"}
LINK_TTL = timedelta(hours=1)      # a link that was not delivered within the hour is dropped (the person asks for a new one)
NOTICE_TTL = timedelta(hours=24)


def enabled(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.smtp_host and s.smtp_from and s.public_base_url)


def _clean(value: str, limit: int) -> str:
    v = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", value).split())
    return v[:limit]


def link_for(token: str, settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return f"{s.public_base_url.rstrip('/')}/convite/{token}"


def render(kind: str, *, organization: str, link: str | None = None, hours: int | None = None, actor: str | None = None) -> tuple[str, str]:
    """(subject, body) for one fixed template. `organization` and `actor` are display names, cleaned of control characters and cut."""
    org = _clean(organization, 60)
    who = _clean(actor, 80) if actor else None
    if kind == "member_invite":
        assert link and hours
        return (f"Convite para {org} no FiberCore",
                f"{who or 'Um administrador'} convidou você para a organização {org} no FiberCore.\n\n"
                f"Abra o link abaixo para criar sua senha e entrar. O link vale por {hours} horas e só pode ser usado uma vez.\n\n{link}\n\n"
                "Se você não esperava este convite, ignore esta mensagem: nada acontece sem o seu acesso ao link.\n")
    if kind == "password_reset":
        assert link and hours
        return (f"Troca de senha no FiberCore ({org})",
                f"Um administrador da organização {org} gerou um link para você escolher uma nova senha.\n\n"
                f"O link vale por {hours} horas e só pode ser usado uma vez.\n\n{link}\n\n"
                "Se você não pediu isso, avise o administrador da sua organização e não abra o link.\n")
    if kind == "mfa_reset_notice":
        return (f"Seu segundo fator foi redefinido ({org})",
                f"O segundo fator de autenticação da sua conta na organização {org} foi redefinido por um administrador.\n\n"
                "No próximo acesso você será pedido a cadastrar um novo. Se você não esperava isso, fale com o administrador da sua organização.\n")
    if kind == "organization_suspended":
        return (f"Organização {org} suspensa no FiberCore",
                f"A organização {org} foi suspensa pelo operador da plataforma. Enquanto durar a suspensão, ninguém consegue entrar nem enviar dados.\n\n"
                "Para saber o motivo ou pedir a reativação, fale com o operador da plataforma.\n")
    if kind == "organization_reactivated":
        return (f"Organização {org} reativada no FiberCore",
                f"A organização {org} foi reativada. O acesso e o envio de dados voltaram ao normal.\n")
    raise ValueError(f"unknown mail kind {kind!r}")


def enqueue(conn: Connection, tenant_id: UUID, kind: str, to_address: str, subject: str, body: str, created_by: UUID | None = None) -> UUID:
    """Queue one message in the caller's transaction (it is sent only if the transaction commits). The address must already be a validated e-mail."""
    to = to_address.strip().lower()
    if not ADDRESS_RE.match(to) or len(to) > 254:
        raise ValueError("invalid address")
    ttl = LINK_TTL if kind in LINK_KINDS else NOTICE_TTL
    new_id = uuid4()
    conn.execute(
        text("INSERT INTO email_queue (tenant_id, id, kind, to_address, subject, body, created_by, expires_at) VALUES (:t, :i, :k, :a, :s, :b, :c, now() + make_interval(secs => :ttl))"),
        {"t": tenant_id, "i": new_id, "k": kind, "a": to, "s": subject, "b": body, "c": created_by, "ttl": ttl.total_seconds()})
    return new_id


def build_message(settings: Settings, to_address: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((_clean(settings.smtp_from_name, 60) or "FiberCore", settings.smtp_from))
    msg["To"] = to_address
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{uuid4().hex}@{settings.smtp_from.rsplit('@', 1)[-1]}>"
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(body)
    return msg


def deliver(settings: Settings, to_address: str, subject: str, body: str) -> None:
    """One SMTP delivery, TLS always (STARTTLS or implicit SSL, certificate verified), short timeouts. Raises on any failure; the caller records only the CLASS of the error."""
    msg = build_message(settings, to_address, subject, body)
    ctx = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=ctx) as smtp:
            _login_send(smtp, settings, msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
            smtp.starttls(context=ctx)
            _login_send(smtp, settings, msg)


def _login_send(smtp: smtplib.SMTP, settings: Settings, msg: EmailMessage) -> None:
    if settings.smtp_user:
        smtp.login(settings.smtp_user, settings.smtp_password)
    smtp.send_message(msg)


# ---------------------------------------------------------------- what each product event sends (all inside the caller's transaction, under the organization's scope)
def _org_name(conn: Connection, tenant_id: UUID) -> str:
    return conn.execute(text("SELECT name FROM tenants WHERE id = :t"), {"t": tenant_id}).scalar_one()


def _display_name(conn: Connection, user_id: UUID | None) -> str | None:
    if user_id is None:
        return None
    return conn.execute(text("SELECT display_name FROM users_global WHERE id = :u"), {"u": user_id}).scalar()


def queue_link(conn: Connection, tenant_id: UUID, kind: str, to_address: str, token: str, hours: int, actor_id: UUID | None, settings: Settings | None = None) -> UUID:
    """A link message (`member_invite` or `password_reset`). The link is built from `PUBLIC_BASE_URL`, never from the request."""
    s = settings or get_settings()
    subject, body = render(kind, organization=_org_name(conn, tenant_id), link=link_for(token, s), hours=hours, actor=_display_name(conn, actor_id))
    return enqueue(conn, tenant_id, kind, to_address, subject, body, actor_id)


def queue_notice(conn: Connection, tenant_id: UUID, kind: str, to_address: str, actor_id: UUID | None = None) -> UUID:
    subject, body = render(kind, organization=_org_name(conn, tenant_id))
    return enqueue(conn, tenant_id, kind, to_address, subject, body, actor_id)


def admin_addresses(conn: Connection, tenant_id: UUID) -> list[str]:
    """The active administrators of the organization (the people a suspension notice is for)."""
    rows = conn.execute(text("SELECT lower(u.email) FROM tenant_memberships m JOIN users_global u ON u.id = m.user_id WHERE m.tenant_id = :t AND m.role = 'isp_admin' AND u.is_active ORDER BY 1"),
                        {"t": tenant_id}).scalars().all()
    return [r for r in rows if ADDRESS_RE.match(r)]
