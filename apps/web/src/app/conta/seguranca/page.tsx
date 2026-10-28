import { AppShell } from "@/components/AppShell";
import { MfaPanel } from "@/components/MfaPanel";
import { ErrorState, PageHeader } from "@/components/ui";
import { apiMfaStatus } from "@/lib/api";

export default async function Seguranca({ searchParams }: { searchParams: Promise<{ obrigatorio?: string }> }) {
  const [st, { obrigatorio }] = await Promise.all([apiMfaStatus(), searchParams]);
  return (
    <AppShell active="/conta/seguranca" user="1">
      <PageHeader title="Segurança da conta" subtitle="Proteja o acesso com um segundo fator" helpSlug="conta/ativar-verificacao-em-duas-etapas" />
      {st === null ? <ErrorState title="Falha ao carregar a segurança da conta" hint="Tente de novo em instantes." /> : (
        <div className="grid max-w-2xl gap-4" data-testid="security-page">
          {(obrigatorio || (st.required && !st.enabled)) && !st.enabled && (
            <div role="status" className="panel border-warn p-4 text-sm" data-testid="mfa-required-banner">
              <strong>Seu perfil exige verificação em duas etapas.</strong> Ative abaixo para voltar a usar o FiberCore. Enquanto isso, as demais telas ficam bloqueadas.
            </div>
          )}
          <MfaPanel enabled={st.enabled} recoveryLeft={st.recovery_codes_left} required={st.required} available={st.enrolment_available} />
        </div>
      )}
    </AppShell>
  );
}
