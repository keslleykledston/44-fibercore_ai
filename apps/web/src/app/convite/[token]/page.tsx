import Link from "next/link";
import { AcceptInvite } from "@/components/AcceptInvite";
import type { InvitePreview } from "@/lib/types";

const API = process.env.API_INTERNAL_URL ?? "http://api-core:8000";
const TOKEN = /^[A-Za-z0-9_-]{20,100}$/;

const PROBLEM: Record<string, { title: string; hint: string }> = {
  invalid: { title: "Link inválido", hint: "Confira se o link foi copiado inteiro. Se continuar, peça um novo a quem convidou você." },
  used: { title: "Este link já foi usado", hint: "Se foi você, é só entrar. Se não foi, avise quem convidou." },
  revoked: { title: "Este convite foi cancelado", hint: "Peça um novo link a quem convidou você." },
  expired: { title: "Este link venceu", hint: "Os links valem por tempo limitado. Peça um novo a quem convidou você." },
};

async function preview(token: string): Promise<InvitePreview | null> {
  if (!TOKEN.test(token)) return { state: "invalid" };
  try {
    const r = await fetch(`${API}/v1/invites/${token}`, { cache: "no-store" });
    if (r.status === 429) return null;
    if (r.status === 404) return { state: "invalid" };
    return r.ok ? ((await r.json()) as InvitePreview) : null;
  } catch { return null; }
}

/** Página PÚBLICA (sem menu, sem sessão): o link é a credencial. */
export default async function Convite({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const p = await preview(token);
  return (
    <main className="mx-auto grid min-h-dvh max-w-md content-center gap-4 px-4 py-8" data-testid="invite-page">
      <div className="panel grid gap-4 p-6">
        <div className="text-sm font-semibold uppercase tracking-wide text-muted">FiberCore</div>
        {p === null ? (
          <div role="alert"><h1 className="text-xl font-semibold">Não foi possível abrir agora</h1><p className="mt-1 text-sm text-muted">Tente de novo em alguns instantes.</p></div>
        ) : p.state !== "valid" ? (
          <div><h1 className="text-xl font-semibold" data-testid="invite-problem">{PROBLEM[p.state].title}</h1><p className="mt-1 text-sm text-muted">{PROBLEM[p.state].hint}</p><Link href="/login" className="mt-4 inline-flex min-h-touch items-center text-accent hover:underline">Ir para o login</Link></div>
        ) : (
          <>
            <div>
              <h1 className="text-xl font-semibold">{p.purpose === "reset" ? "Trocar a senha" : `Entrar na equipe de ${p.tenant_name}`}</h1>
              {p.purpose === "invite" && <p className="mt-1 text-sm text-muted">{p.inviter ? `${p.inviter} convidou você` : "Você foi convidado"} como <strong className="text-text">{p.role_label}</strong>.</p>}
              {p.purpose === "reset" && <p className="mt-1 text-sm text-muted">Link gerado por um administrador de {p.tenant_name}.</p>}
            </div>
            <AcceptInvite token={token} purpose={p.purpose} accountExists={p.account_exists} email={p.email} defaultName={p.name} />
          </>
        )}
      </div>
    </main>
  );
}
