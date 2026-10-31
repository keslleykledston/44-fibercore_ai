import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { Card, Row } from "@/components/Panel";
import { SourceChip } from "@/components/SourceChip";
import { DataFreshness, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { CapabilityGate } from "@/components/CapabilityGate";
import { OntSidebar } from "@/components/OntSidebar";
import { humanHours } from "@/lib/offline";
import type { Capability, Onu360, OnuCustomer, OnuHistory } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STATE: Record<string, string> = { online: "online", offline: "fora do ar", los: "sem sinal (LOS)", dying_gasp: "falta de energia", unknown: "desconhecido" };
const cause: Record<string, string> = { fiber_or_los: "Suspeita: perda de sinal / fibra", power: "Suspeita: falta de energia", unknown: "Causa não determinada" };
const contract: Record<string, string> = { active: "Contrato ativo", suspended: "Contrato suspenso", cancelled: "Contrato cancelado", unknown: "Contrato não informado" };
const when = (iso: string | null) => (iso ? <span data-testid="volatile">{new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</span> : "—");

const cpeErr: Record<string, string> = { "403": "Seu papel não permite revisar vínculos.", "409": "Este vínculo mudou ou é ambíguo; recarregue e confira o inventário." };

export default async function Onu360Page({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ cpe?: string; cpe_erro?: string }> }) {
  const { id } = await params;
  const { cpe: cpeDone, cpe_erro: cpeFail } = await searchParams;
  if (!UUID.test(id)) notFound();
  // O assinante é dado pessoal: rota própria (customers:read, auditada). 403 = papel sem acesso => o bloco simplesmente não aparece.
  const [r, cu] = await Promise.all([apiSafe<Onu360>(`/v1/onus/${id}`), apiSafe<OnuCustomer>(`/v1/onus/${id}/customer`)]);
  if (r.status === 404) notFound();
  if (r.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
  const o = r.data;
  const customer = cu.status === 200 ? cu.data : null;
  const customerFailed = cu.status !== 200 && cu.status !== 403; // só 403 (papel sem acesso) omite o bloco; o resto é falha e aparece
  if (!o) return <AppShell active="/rede" user="1"><ErrorState title="Falha ao carregar a ONU" hint="Tente novamente em instantes." /></AppShell>;
  const caps = await apiSafe<Capability[]>(`/v1/olts/${o.olt.id}/capabilities`);  // perfil da OLT da ONU (registro de capacidades)
  const hist = await apiSafe<OnuHistory>(`/v1/onus/${id}/history?days=30&limit=12`);
  const ontCfg = o.cpe?.link === "confirmed" && o.cpe.device ? await apiSafe<{ enabled: boolean }>("/v1/ont-config/health") : null;   // o botão só existe com o recurso ligado
  return (
    <AppShell active="/rede" user="1">
      <PageHeader title={`ONU ${o.serial}`} subtitle="Visão completa de uma ONU, com a origem de cada dado" helpSlug="rede/onu-360">
        <Link href="/rede" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para Rede</Link>
      </PageHeader>
      <div data-testid="onu360-ready" className="grid gap-4 md:grid-cols-2">
        <Card title="Estado" testid="onu360-state">
          <dl>
            <Row k="Status"><StatusPill value={o.status} /></Row>
            <Row k="Potência recebida (Rx)">{o.rx_dbm !== null ? `${o.rx_dbm} dBm` : "—"}</Row>
            <Row k="Último dado"><DataFreshness freshness={o.freshness} observedAt={o.observed_at} /></Row>
            <Row k="Visto online pela última vez">{when(o.last_online_at)}</Row>
            {o.down_since && <Row k="Fora do ar desde">{when(o.down_since)}</Row>}
            <Row k="Origem do dado"><SourceChip p={o.provenance.state} /></Row>
          </dl>
        </Card>
        <Card title="Localização" testid="onu360-location">
          <dl>
            <Row k="OLT">{o.olt.name}</Row>
            <Row k="Equipamento">{o.olt.vendor} {o.olt.model ?? ""}{o.olt.firmware ? ` · ${o.olt.firmware}` : ""}</Row>
            <Row k="Nível do driver"><StatusPill value={o.olt.support_level} /></Row>
            <Row k="PON">{o.pon?.path ?? "—"}</Row>
            {o.pon && <Row k="ONUs na PON"><span>{o.pon.online} online de {o.pon.onus}</span> {o.provenance.pon && <SourceChip p={o.provenance.pon} />}{o.pon.freshness === "stale" && <span className="block text-xs text-warn">Último estado conhecido, não o atual.</span>}</Row>}
            <Row k="Coleta da OLT"><SourceChip p={o.provenance.olt} /></Row>
          </dl>
        </Card>
        <Card title="Histórico (30 dias)" testid="onu360-history">
          {hist.data === null ? <p className="text-sm text-muted">O histórico não está disponível agora.</p> : (
            <div className="grid gap-3 text-sm">
              <dl>
                <Row k="Quedas">{hist.data.summary.drops}</Row>
                <Row k="Tempo fora do ar">{humanHours(hist.data.summary.offline_hours)}</Row>
                <Row k="Disponibilidade">{hist.data.summary.availability_pct === null ? "—" : `${hist.data.summary.availability_pct.toLocaleString("pt-BR")}%`}</Row>
              </dl>
              <ol className="divide-y divide-line" aria-label="Mudanças de estado, da mais recente para a mais antiga">
                {hist.data.events.map((e) => (
                  <li key={e.id} className="py-1.5">
                    <span className="font-medium">{e.baseline ? `Primeira observação: ${STATE[e.to] ?? e.to}` : e.to === "online" ? "Voltou a ficar online" : e.to === "unknown" ? "Estado deixou de ser conhecido" : "Ficou fora do ar"}</span>
                    <span className="block text-xs text-muted">{when(e.at)}</span>
                  </li>
                ))}
              </ol>
              <p className="text-xs text-muted">Conta o que o Edge observou: uma queda e a volta entre duas coletas não aparecem. {hist.data.truncated ? "Mostrando as mais recentes." : ""}</p>
            </div>
          )}
        </Card>
        <Card title="Incidente" testid="onu360-incident">
          {o.incident ? (
            <div className="text-sm">
              <p className="font-medium text-danger">Esta ONU faz parte de um incidente em massa aberto.</p>
              <p className="mt-1 text-muted">{cause[o.incident.suspected_cause] ?? cause.unknown} · aberto em {when(o.incident.opened_at)}</p>
              <Link href="/noc" className="mt-3 inline-flex min-h-touch items-center rounded-btn text-accent hover:underline">Ver no NOC</Link>
            </div>
          ) : o.incident_hidden ? <p className="text-sm text-muted">Seu papel não permite ver incidentes.</p>
            : <p className="text-sm text-muted">Nenhum incidente aberto envolve esta ONU.</p>}
        </Card>
        {customerFailed && (
          <Card title="Assinante" testid="onu360-customer-error">
            <div role="alert"><p className="text-sm font-medium text-danger">Não foi possível carregar o assinante desta ONU.</p>
              <p className="mt-1 text-sm text-muted">Isso não significa que não haja vínculo. Recarregue a página para tentar de novo.</p></div>
          </Card>
        )}
        {customer && (
          <Card title="Assinante" testid="onu360-customer">
            {customer.association === "approved" ? (
              <dl>
                <Row k="Nome">{customer.display_name}</Row>
                {customer.document_last4 && <Row k="Documento">final {customer.document_last4}</Row>}
                <Row k="Situação">{contract[customer.contract_status ?? "unknown"] ?? contract.unknown}</Row>
              </dl>
            ) : customer.association === "suggested" ? (
              <p className="text-sm">Há {customer.pending_suggestions} sugestão(ões) de vínculo aguardando revisão. <Link href="/assinantes" className="text-accent underline underline-offset-2">Revisar em Assinantes</Link></p>
            ) : <p className="text-sm text-muted">Nenhum assinante vinculado a esta ONU.</p>}
            <p className="mt-3 text-xs text-muted">O acesso a dados de assinante fica registrado na auditoria.</p>
          </Card>
        )}
        {o.cpe && o.cpe.link !== "unavailable" && (
          <Card title="Roteador (CPE)" testid="onu360-cpe">
            {cpeDone && <p role="status" className="mb-2 text-sm text-ok">{cpeDone === "confirm" ? "Vínculo confirmado." : "Sugestão rejeitada."}</p>}
            {cpeFail && <p role="alert" className="mb-2 text-sm text-danger">{cpeErr[cpeFail] ?? "Não foi possível concluir a revisão."}</p>}
            {o.cpe.link === "confirmed" && o.cpe.device ? (
              <>
                <dl>
                  <Row k="Equipamento">{o.cpe.device.vendor ?? "—"} {o.cpe.device.model ?? ""}{o.cpe.device.firmware ? ` · ${o.cpe.device.firmware}` : ""}</Row>
                  <Row k="Gerência">{o.cpe.device.protocols.length ? o.cpe.device.protocols.join(", ").toUpperCase() : "—"}</Row>
                  {o.cpe.provenance && <Row k="Origem do dado"><SourceChip p={o.cpe.provenance} /></Row>}
                </dl>
                {ontCfg?.data?.enabled && (
                  <OntSidebar key={o.cpe.device.id} cpeId={o.cpe.device.id} identity={`${o.cpe.device.vendor ?? ""} ${o.cpe.device.model ?? ""}${o.cpe.device.firmware ? ` · ${o.cpe.device.firmware}` : ""}`.trim() || "Aparelho"} />
                )}
              </>
            ) : o.cpe.link === "suggested" ? (
              <ul className="space-y-3 text-sm">
                {o.cpe.suggestions.map((s) => (
                  <li key={s.id}>
                    <p>Há um roteador com o <strong>mesmo serial</strong> desta ONU. Igualdade de serial é um indício, não uma prova (confiança {Math.round(s.confidence * 100)}%).</p>
                    {s.ambiguous && <p className="mt-1 text-warn">Ambíguo: este serial existe em mais de uma OLT. Resolva o inventário antes de confirmar.</p>}
                    {o.cpe?.can_review ? (
                      <div className="mt-2 flex flex-wrap gap-2">
                        {!s.ambiguous && (
                          <form action={`/bff/onu-cpe-links/${s.id}/confirm?onu=${o.id}`} method="post"><button data-testid="cpe-confirm" className="min-h-touch rounded-btn bg-accent px-3 text-[color:var(--on-accent)]">Confirmar vínculo</button></form>
                        )}
                        <form action={`/bff/onu-cpe-links/${s.id}/reject?onu=${o.id}`} method="post"><button data-testid="cpe-reject" className="min-h-touch rounded-btn border border-line px-3">Rejeitar</button></form>
                      </div>
                    ) : <p className="mt-1 text-muted">Seu papel não permite revisar vínculos.</p>}
                  </li>
                ))}
                {o.cpe.has_more_suggestions && <li className="text-warn" data-testid="cpe-more">Há {o.cpe.pending_suggestions} sugestões no total; esta tela mostra as {o.cpe.suggestions.length} de maior confiança. Revise estas para ver as demais.</li>}
              </ul>
            ) : <p className="text-sm text-muted">Nenhum roteador vinculado a esta ONU.</p>}
            <p className="mt-3 text-xs text-muted">O vínculo ONU↔CPE só vale depois de confirmado por uma pessoa. Nada aqui altera a rede.</p>
          </Card>
        )}
        <Card title="Ações" testid="onu360-actions">
          <p className="text-sm">Nenhuma ação de escrita está liberada para esta ONU.</p>
          <p className="mt-1 text-sm text-muted">Reinício, troca de Wi-Fi e outras escritas na rede ficam bloqueadas até a homologação do driver e a política de aprovação. Gerência remota TR-069/TR-369: não homologada.</p>
          <Link href="/operacoes" className="mt-3 inline-flex min-h-touch items-center rounded-btn text-accent underline underline-offset-2">Ver Operações</Link>
          {caps.data ? <CapabilityGate caps={caps.data} title="Capacidades da OLT desta ONU" />
            : caps.status === 403 ? null  /* recurso desligado para este provedor (flag) ou sem permissão: o bloco simplesmente não existe */
            : <p role="alert" className="mt-4 border-t border-line pt-3 text-sm text-danger" data-testid="capability-error">Não foi possível carregar as capacidades. Isso não significa que sejam suportadas.</p>}
        </Card>
      </div>
    </AppShell>
  );
}
