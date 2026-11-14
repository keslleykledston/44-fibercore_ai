import { AdminTabs } from "@/components/AdminTabs";
import { AppShell } from "@/components/AppShell";
import { PolicyForm } from "@/components/PolicyForm";
import { ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { roleName } from "@/lib/orgSecurity";
import type { SecurityPolicy } from "@/lib/types";

export default async function SegurancaDaOrganizacao() {
  const r = await apiSafe<SecurityPolicy>("/v1/security-policy");
  return (
    <AppShell active="/administracao/modulos" user="1">
      <PageHeader title="Segurança da organização" subtitle="Quem precisa da verificação em duas etapas" helpSlug="administracao/seguranca-da-organizacao" />
      <AdminTabs current="/administracao/seguranca" />
      {r.status === 403 ? <ErrorState title="Sem permissão" hint="Seu papel não permite ver esta política." /> : r.data === null ? <ErrorState title="Falha ao carregar a política" hint="Tente de novo em instantes." /> : (
        <div className="grid gap-4" data-testid="policy-ready">
          <section className="panel p-4 text-sm" aria-labelledby="h-floor">
            <h2 id="h-floor" className="font-semibold">O que a plataforma já exige</h2>
            <p className="mt-1 text-muted" data-testid="policy-floor">{r.data.floor.length === 0 ? "Nenhuma função é exigida pela plataforma." : r.data.floor.map(roleName).join(", ") + "."} Isto vale para todas as organizações e não dá para tirar.</p>
          </section>
          <PolicyForm policy={r.data} />
        </div>
      )}
    </AppShell>
  );
}
