import Link from "next/link";
import { AdminTabs } from "@/components/AdminTabs";
import { ApiTokens } from "@/components/ApiTokens";
import { AppShell } from "@/components/AppShell";
import { Webhooks } from "@/components/Webhooks";
import { ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import type { ApiTokenList, WebhookList } from "@/lib/types";

type Search = { aba?: string };
const TABS = [{ id: "tokens", label: "Tokens de API" }, { id: "webhooks", label: "Webhooks" }];

export default async function Integracoes({ searchParams }: { searchParams: Promise<Search> }) {
  const aba = (await searchParams).aba === "webhooks" ? "webhooks" : "tokens";
  const tokens = aba === "tokens" ? await apiSafe<ApiTokenList>("/v1/api-tokens") : null;
  const hooks = aba === "webhooks" ? await apiSafe<WebhookList>("/v1/webhooks") : null;
  const res = tokens ?? hooks!;
  return (
    <AppShell active="/administracao/modulos" user="1">
      <PageHeader title="Integrações" subtitle="Tokens de API (só leitura) e webhooks de saída" helpSlug="administracao/integracoes" />
      <AdminTabs current="/administracao/integracoes" />
      <nav aria-label="Seções das integrações" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((t) => (
          <Link key={t.id} href={`/administracao/integracoes?aba=${t.id}`} aria-current={t.id === aba ? "page" : undefined} data-testid={`int-tab-${t.id}`}
            className={`inline-flex min-h-touch items-center whitespace-nowrap px-4 text-sm ${t.id === aba ? "border-b-2 border-accent font-medium text-text" : "text-muted hover:text-text"}`}>{t.label}</Link>
        ))}
      </nav>
      {res.status === 403 ? <ErrorState title="Sem permissão" hint="Só o Administrador do provedor gerencia integrações." /> : res.data === null ? <ErrorState title="Falha ao carregar" hint="Tente de novo em instantes." /> : (
        aba === "tokens" ? <ApiTokens data={tokens!.data!} /> : <Webhooks data={hooks!.data!} />
      )}
    </AppShell>
  );
}
