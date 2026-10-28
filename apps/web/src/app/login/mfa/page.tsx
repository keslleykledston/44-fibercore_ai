import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { MFA_COOKIE } from "@/lib/session";

export default async function LoginMfa({ searchParams }: { searchParams: Promise<{ erro?: string }> }) {
  if (!(await cookies()).get(MFA_COOKIE)) redirect("/login");
  const { erro } = await searchParams;
  return (
    <main className="mx-auto grid min-h-screen max-w-sm content-center gap-6 px-4">
      <h1 className="text-2xl font-semibold tracking-tight">Verificação em duas etapas</h1>
      <form action="/bff/mfa" method="post" className="panel grid gap-4 p-6" data-testid="mfa-form">
        {erro && <p role="alert" className="text-sm text-danger" data-testid="mfa-error">{erro === "429" ? "Muitas tentativas. Aguarde 15 minutos e tente de novo." : "Código inválido."}</p>}
        <label className="grid gap-1 text-sm">Código do aplicativo autenticador ou código de recuperação
          <input name="code" required autoComplete="one-time-code" inputMode="text" autoFocus className="min-h-touch rounded-btn border border-line bg-bg px-3 tabular-nums" />
        </label>
        <button type="submit" className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">Verificar</button>
        <a href="/login" className="text-sm text-muted underline">Voltar ao login</a>
      </form>
    </main>
  );
}
