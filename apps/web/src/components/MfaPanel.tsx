"use client";
import { useState, type FormEvent } from "react";

type Props = { enabled: boolean; recoveryLeft: number; required: boolean; available: boolean };
type Step = "idle" | "scan" | "codes";

async function post(path: string, body: unknown): Promise<{ status: number; json: Record<string, unknown> }> {
  const res = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), cache: "no-store", credentials: "same-origin" });
  return { status: res.status, json: ((await res.json().catch(() => ({}))) ?? {}) as Record<string, unknown> };
}

const MESSAGES: Record<string, string> = {
  invalid: "Senha ou código incorretos.",
  throttled: "Muitas tentativas. Aguarde 15 minutos e tente de novo.",
  conflict: "Esta ação não é permitida: a verificação já está ativa, ou é obrigatória para o seu perfil e não pode ser desativada.",
  unavailable: "O cadastro de verificação em duas etapas não está disponível neste ambiente. Avise o administrador da plataforma.",
  session: "Sua sessão expirou. Recarregue a página e tente de novo.",
  bad_request: "Confira os campos e tente de novo.",
};
const explain = (j: Record<string, unknown>) => MESSAGES[String(j.error)] ?? "Não foi possível concluir. Tente de novo em instantes.";
const groups = (s: string) => s.replace(/\s+/g, "").replace(/(.{4})/g, "$1 ").trim();

export function MfaPanel({ enabled, recoveryLeft, required, available }: Props) {
  const [step, setStep] = useState<Step>("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [qr, setQr] = useState("");
  const [secret, setSecret] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [regen, setRegen] = useState(false);

  async function run(e: FormEvent<HTMLFormElement>, fn: (f: FormData) => Promise<void>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    setBusy(true); setError("");
    try { await fn(data); } catch { setError(MESSAGES.session); } finally { setBusy(false); }
  }

  const enrol = (e: FormEvent<HTMLFormElement>) => run(e, async (f) => {
    const r = await post("/bff/security/mfa/enroll", { password: String(f.get("password") ?? "") });
    if (r.status !== 200) return setError(explain(r.json));
    setSecret(String(r.json.secret)); setQr(String(r.json.qr)); setStep("scan");
  });
  const activate = (e: FormEvent<HTMLFormElement>) => run(e, async (f) => {
    const r = await post("/bff/security/mfa/activate", { code: String(f.get("code") ?? "") });
    if (r.status !== 200) return setError(explain(r.json));
    setSecret(""); setQr(""); setCodes(r.json.recovery_codes as string[]); setStep("codes");
  });
  const regenerate = (e: FormEvent<HTMLFormElement>) => run(e, async (f) => {
    const r = await post("/bff/security/mfa/recovery-codes", { password: String(f.get("password") ?? ""), code: String(f.get("code") ?? "") });
    if (r.status !== 200) return setError(explain(r.json));
    setRegen(true); setCodes(r.json.recovery_codes as string[]); setStep("codes");
  });
  const disable = (e: FormEvent<HTMLFormElement>) => run(e, async (f) => {
    const r = await post("/bff/security/mfa/disable", { password: String(f.get("password") ?? ""), code: String(f.get("code") ?? "") });
    if (r.status !== 200) return setError(explain(r.json));
    window.location.assign("/conta/seguranca");
  });

  const text = codes.join("\n");
  const copy = async () => { try { await navigator.clipboard.writeText(text); setCopied(true); } catch { setError("Não foi possível copiar. Selecione os códigos e copie manualmente."); } };
  const download = () => {
    const url = URL.createObjectURL(new Blob([`FiberCore - códigos de recuperação (uso único)\n\n${text}\n`], { type: "text/plain" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: "fibercore-codigos-de-recuperacao.txt" });
    a.click(); URL.revokeObjectURL(url);
  };

  const input = "min-h-touch w-full rounded-btn border border-line bg-bg px-3";
  const primary = "min-h-touch rounded-btn bg-accent px-4 font-medium text-[color:var(--on-accent)] disabled:opacity-50";
  const err = error && <p role="alert" className="text-sm text-danger" data-testid="mfa-error">{error}</p>;

  if (step === "codes") {
    return (
      <section className="panel grid gap-4 p-6" aria-labelledby="mfa-titulo" data-testid="mfa-codes-step">
        <h2 id="mfa-titulo" className="text-lg font-semibold">Guarde seus códigos de recuperação</h2>
        <p className="text-sm text-muted">{regen ? "Estes são os seus novos códigos; os anteriores deixaram de valer." : "Verificação em duas etapas ativada."} Cada código funciona <strong>uma única vez</strong> e serve se você perder o aplicativo autenticador. Eles <strong>não serão mostrados de novo</strong>.</p>
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2" data-testid="mfa-recovery-codes">
          {codes.map((c) => <li key={c} className="rounded-btn border border-line bg-surface-2 px-3 py-2 font-mono text-sm tabular-nums">{c}</li>)}
        </ul>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={copy} className="min-h-touch rounded-btn border border-line px-4 text-sm">{copied ? "Copiado" : "Copiar"}</button>
          <button type="button" onClick={download} className="min-h-touch rounded-btn border border-line px-4 text-sm">Baixar .txt</button>
        </div>
        {err}
        <label className="flex min-h-touch items-center gap-3 text-sm">
          <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} data-testid="mfa-saved" className="size-5" />
          Guardei os códigos em um lugar seguro
        </label>
        <button type="button" disabled={!saved} onClick={() => window.location.assign("/conta/seguranca")} className={primary} data-testid="mfa-done">Concluir</button>
      </section>
    );
  }

  if (step === "scan") {
    return (
      <section className="panel grid gap-4 p-6" aria-labelledby="mfa-titulo" data-testid="mfa-scan-step">
        <h2 id="mfa-titulo" className="text-lg font-semibold">Escaneie o QR code</h2>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
          <li>No celular, abra um aplicativo autenticador (por exemplo, Google Authenticator, Microsoft Authenticator ou Aegis).</li>
          <li>Adicione uma conta e escaneie o QR code abaixo. Se não puder escanear, digite a chave manualmente.</li>
          <li>Digite o código de 6 dígitos que o aplicativo mostrar.</li>
        </ol>
        <div className="grid items-center gap-4 sm:grid-cols-[auto_1fr]">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={qr} alt="QR code para cadastrar o FiberCore no aplicativo autenticador" width={224} height={224} className="rounded-btn border border-line bg-white" data-testid="mfa-qr" />
          <div className="grid gap-1 text-sm">
            <span className="text-muted">Chave para digitar manualmente</span>
            <code className="break-all font-mono text-base tabular-nums" data-testid="mfa-secret">{groups(secret)}</code>
          </div>
        </div>
        <form onSubmit={activate} className="grid gap-3" data-testid="mfa-activate-form">
          <label className="grid gap-1 text-sm">Código de 6 dígitos
            <input name="code" required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,8}" maxLength={8} autoFocus className={`${input} tabular-nums`} data-testid="mfa-code" />
          </label>
          {err}
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={busy} className={primary} data-testid="mfa-activate">Confirmar e ativar</button>
            <button type="button" onClick={() => { setStep("idle"); setError(""); setSecret(""); setQr(""); }} className="min-h-touch rounded-btn border border-line px-4 text-sm">Cancelar</button>
          </div>
        </form>
      </section>
    );
  }

  if (enabled) {
    return (
      <section className="panel grid gap-4 p-6" aria-labelledby="mfa-titulo">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="mfa-titulo" className="text-lg font-semibold">Verificação em duas etapas</h2>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-ok-soft px-2.5 py-0.5 text-xs font-medium text-ok" data-testid="mfa-status"><span aria-hidden>●</span>Ativa</span>
        </div>
        <p className="text-sm text-muted">Ao entrar, além da senha, você informa um código do aplicativo autenticador.</p>
        <p className="text-sm" data-testid="mfa-left">Códigos de recuperação restantes: <strong>{recoveryLeft}</strong>{recoveryLeft <= 2 && <span className="ml-2 text-warn">▲ Poucos códigos restantes. Peça ao administrador para reconfigurar se acabarem.</span>}</p>
        <details className="rounded-btn border border-line p-3">
          <summary className="min-h-touch cursor-pointer text-sm font-medium">Gerar novos códigos de recuperação</summary>
          <form onSubmit={regenerate} className="mt-3 grid gap-3" data-testid="mfa-regen-form">
            <p className="text-sm text-muted">Os códigos atuais deixam de valer. Os novos aparecem uma única vez.</p>
            <label className="grid gap-1 text-sm">Senha atual
              <input name="password" type="password" required autoComplete="current-password" className={input} data-testid="mfa-regen-password" />
            </label>
            <label className="grid gap-1 text-sm">Código do aplicativo ou código de recuperação
              <input name="code" required autoComplete="one-time-code" className={`${input} tabular-nums`} data-testid="mfa-regen-code" />
            </label>
            {error && <p role="alert" className="text-sm text-danger" data-testid="mfa-regen-error">{error}</p>}
            <button type="submit" disabled={busy} className="min-h-touch rounded-btn border border-line px-4 font-medium disabled:opacity-50" data-testid="mfa-regen">Gerar novos códigos</button>
          </form>
        </details>
        {required ? (
          <p className="rounded-btn bg-accent-soft p-3 text-sm" data-testid="mfa-required-note">Esta verificação é <strong>obrigatória para o seu perfil</strong> e não pode ser desativada.</p>
        ) : (
          <details className="rounded-btn border border-line p-3">
            <summary className="min-h-touch cursor-pointer text-sm font-medium">Desativar verificação em duas etapas</summary>
            <form onSubmit={disable} className="mt-3 grid gap-3" data-testid="mfa-disable-form">
              <label className="grid gap-1 text-sm">Senha atual
                <input name="password" type="password" required autoComplete="current-password" className={input} data-testid="mfa-disable-password" />
              </label>
              <label className="grid gap-1 text-sm">Código do aplicativo ou código de recuperação
                <input name="code" required autoComplete="one-time-code" className={`${input} tabular-nums`} data-testid="mfa-disable-code" />
              </label>
              {err}
              <button type="submit" disabled={busy} className="min-h-touch rounded-btn border border-danger px-4 font-medium text-danger disabled:opacity-50" data-testid="mfa-disable">Desativar</button>
            </form>
          </details>
        )}
      </section>
    );
  }

  return (
    <section className="panel grid gap-4 p-6" aria-labelledby="mfa-titulo">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="mfa-titulo" className="text-lg font-semibold">Verificação em duas etapas</h2>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-stale-soft px-2.5 py-0.5 text-xs font-medium text-muted" data-testid="mfa-status"><span aria-hidden>○</span>Desativada</span>
      </div>
      <p className="text-sm text-muted">Protege a conta mesmo se a senha vazar: o login passa a exigir também um código gerado no seu celular.</p>
      {!available ? (
        <p role="alert" className="text-sm text-danger" data-testid="mfa-unavailable">{MESSAGES.unavailable}</p>
      ) : (
        <form onSubmit={enrol} className="grid gap-3" data-testid="mfa-enrol-form">
          <label className="grid gap-1 text-sm">Confirme sua senha para continuar
            <input name="password" type="password" required autoComplete="current-password" className={input} data-testid="mfa-enrol-password" />
          </label>
          {err}
          <button type="submit" disabled={busy} className={primary} data-testid="mfa-enrol">Ativar verificação em duas etapas</button>
        </form>
      )}
    </section>
  );
}
