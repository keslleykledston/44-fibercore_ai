import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { CapabilityGate } from "@/components/CapabilityGate";
import { Card, Row } from "@/components/Panel";
import { DevicesTabs } from "@/components/DevicesTabs";
import { DataFreshness, ErrorState, PageHeader } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { isUuid, metricLabel, metricValue, protocolLabel } from "@/lib/devices";
import type { Capability, Cpe, CpeStateView, OnuCpeLink } from "@/lib/types";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short", timeZone: "America/Sao_Paulo" }) : "—");

export default async function CpeDetalhe({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isUuid(id)) notFound();
  const [list, state, caps, links] = await Promise.all([
    apiSafe<Cpe>(`/v1/cpes/${id}`), apiSafe<CpeStateView>(`/v1/cpes/${id}/state`), apiSafe<Capability[]>(`/v1/cpes/${id}/capabilities`),
    apiSafe<OnuCpeLink[]>("/v1/onu-cpe-links?status=confirmed&limit=1000"),
  ]);
  if (list.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
  if (list.status === 404) notFound();
  const cpe = list.data;
  if (!cpe) return <AppShell active="/rede" user="1"><ErrorState title="Falha ao carregar o CPE" hint="Tente novamente em instantes." /></AppShell>;
  const link = links.data?.find((l) => l.cpe.id === id) ?? null; // flag onu_cpe_links desligada (403) => o bloco diz que não está disponível
  const metrics = state.data?.metrics ?? [];
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title={`CPE ${cpe.canonical_serial}`} subtitle="Identidade, estado lido no ACS e capacidades (somente leitura)" helpSlug="rede/dispositivos">
        <Link href="/dispositivos" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para Dispositivos</Link>
      </PageHeader>
      <DevicesTabs current="/dispositivos" />
      <div data-testid="cpe360-ready" className="grid gap-4 md:grid-cols-2">
        <Card title="Identidade" testid="cpe-identity">
          <dl>
            <Row k="Serial">{cpe.canonical_serial}</Row>
            <Row k="Fabricante">{cpe.vendor ?? "—"}</Row>
            <Row k="Modelo">{cpe.model ?? "—"}</Row>
            <Row k="Firmware">{cpe.firmware ?? "—"}</Row>
            <Row k="Dado"><DataFreshness freshness={cpe.freshness} observedAt={cpe.observed_at} /></Row>
            {cpe.bindings.map((b) => <Row key={`${b.connector_id}-${b.external_id}`} k={protocolLabel(b.protocol)}><span className="break-all font-mono text-xs">{b.external_id}</span></Row>)}
          </dl>
        </Card>
        <Card title="ONU vinculada" testid="cpe-link">
          {links.status === 403 || links.status === 409 ? <p className="text-sm text-muted">O vínculo ONU↔CPE não está habilitado para este provedor.</p>
            : link ? <dl><Row k="ONU"><Link href={`/rede/onu/${link.onu.id}`} className="font-mono text-accent hover:underline">{link.onu.serial}</Link></Row><Row k="Vínculo">Confirmado por uma pessoa</Row></dl>
            : <p className="text-sm text-muted">Nenhum vínculo confirmado. Sugestões são revisadas na ONU 360.</p>}
        </Card>
        <Card title="Estado lido no ACS" testid="cpe-state">
          {state.data === null ? <p className="text-sm text-danger">Falha ao ler o estado.</p> : metrics.length === 0 ? <p className="text-sm text-muted">Nenhuma leitura de estado deste CPE ainda. Ausência de leitura não é “tudo certo”.</p> : (
            <table className="w-full text-sm">
              <caption className="sr-only">Métricas lidas do cache do ACS</caption>
              <thead className="text-left text-muted"><tr><th scope="col" className="py-1 font-medium">Métrica</th><th scope="col" className="py-1 font-medium">Valor</th><th scope="col" className="py-1 font-medium">Lido em</th></tr></thead>
              <tbody className="divide-y divide-line">
                {metrics.map((m) => (
                  <tr key={`${m.metric}-${m.scope}`}>
                    <td className="py-1.5">{metricLabel(m.metric)}{m.scope ? <span className="text-xs text-muted"> · {m.scope}</span> : null}</td>
                    <td className="py-1.5">{metricValue(m.metric, m.value)}</td>
                    <td className={`py-1.5 text-xs ${m.fresh ? "text-muted" : "text-warn"}`}>{when(m.captured_at)}{m.fresh ? "" : " · defasado"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Capacidades" testid="cpe-capabilities">
          {caps.data ? <CapabilityGate caps={caps.data} title="Operações neste perfil" /> : <p className="text-sm text-muted">O registro de capacidades não está disponível.</p>}
          <p className="mt-3 text-xs text-muted">Ações que alteram o equipamento ficam em Operações e só valem para o que está homologado para o alvo.</p>
        </Card>
      </div>
    </AppShell>
  );
}
