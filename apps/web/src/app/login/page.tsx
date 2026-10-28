export default async function Login({ searchParams }: { searchParams: Promise<{ erro?: string }> }) {
  const { erro } = await searchParams;
  return (
    <main className="mx-auto grid min-h-screen max-w-sm content-center gap-6 px-4">
      <h1 className="text-2xl font-semibold tracking-tight">Entrar no FiberCore</h1>
      <form action="/bff/login" method="post" className="panel grid gap-4 p-6" data-testid="login-form">
        {erro && <p role="alert" className="text-sm text-danger" data-testid="login-error">{erro === "429" ? "Muitas tentativas. Aguarde 15 minutos e tente de novo." : "E-mail ou senha inválidos."}</p>}
        <label className="grid gap-1 text-sm">E-mail
          <input name="email" type="email" required autoComplete="username" className="min-h-touch rounded-btn border border-line bg-bg px-3" />
        </label>
        <label className="grid gap-1 text-sm">Senha
          <input name="password" type="password" required autoComplete="current-password" className="min-h-touch rounded-btn border border-line bg-bg px-3" />
        </label>
        <button type="submit" className="min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)]">Entrar</button>
      </form>
    </main>
  );
}
