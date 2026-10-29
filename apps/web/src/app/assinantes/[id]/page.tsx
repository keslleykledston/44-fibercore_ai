import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { Card, Row } from "@/components/Panel";
import { SourceChip } from "@/components/SourceChip";
import { EmptyState, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { diagnosticsOn, subscriber360On } from "@/lib/features";
import type { CustomerContext, CustomerOnu } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TABS = [["conexao", "Conexão"], ["optica", "Óptica"], ["cpe", "Roteador (CPE)"], ["cliente", "Cliente"], ["acoes", "Ações"]] as const;
/** Abas só onde há dado (FC22-005): sem ONU não há Conexão/Óptica/Ações; sem Rx não há Óptica; sem equipamento confirmado/candidato não há CPE. */
const tabsFor = (o: CustomerOnu | undefined) => TABS.filter(([t]) => t === "cliente" || (!!o && (t === "conexao" || t === "acoes" || (t === "optica" && o.rx_dbm !== null) || (t === "cpe" && o.cpe.link !== "unavailable"))));
const TONE: Record<CustomerContext["status"], string> = { complete: "bg-ok-soft text-ok", partial: "bg-warn-soft text-warn", stale: "bg-warn-soft text-warn", unknown: "bg-stale-soft text-muted" };
const STATE: Record<string, string> = { online: "Online", offline: "Offline", los: "Fora · LOS", dying_gasp: "Fora · sinal de energia (dying-gasp)" };
const OVERALL: Record<CustomerContext["status"], { label: string; icon: string; why: string }> = {
  complete: { label: "Completo", icon: "●", why: "Contrato, ONU e roteador confirmados, todos com dado recente." },
  partial: { label: "Parcial", icon: "½", why: "Falta confirmar o roteador de ao menos uma ONU, ou há ONUs que esta tela não mostra." },
  stale: { label: "Defasado", icon: "▲", why: "Algum dado está velho: leia como o último estado conhecido, não como o estado de agora." },
  unknown: { label: "Desconhecido", icon: "○", why: "Nenhuma ONU aprovada para este cliente: não afirmamos nada sobre a conexão." },
};
const contract: Record<string, string> = { active: "Contrato ativo", suspended: "Contrato suspenso", cancelled: "Contrato cancelado", unknown: "Contrato não informado" };
const cause: Record<string, string> = { fiber_or_los: "Suspeita: perda de sinal / fibra", power: "Suspeita: falta de energia", unknown: "Causa não determinada" };

function Tab({ id, cur, onu, children }: { id: string; cur: string; onu: string; children: React.ReactNode }) {
  const on = id === cur;
  return <a href={`?aba=${id}&onu=${onu}`} aria-current={on ? "page" : undefined} data-testid={`tab-${id}`}
    className={`inline-flex min-h-touch items-center rounded-btn px-3 text-sm ${on ? "bg-accent-soft font-medium text-accent" : "text-muted hover:underline"}`}>{children}</a>;
}

function Panel({ tab, o }: { tab: string; o: CustomerOnu }) {
  if (tab === "optica") return (
    <Card title="Óptica" testid="sub-optica"><dl>
      <Row k="Potência recebida (Rx)"><span className="text-3xl font-semibold tabular-nums">{o.rx_dbm !== null ? o.rx_dbm : "—"}</span> <span className="text-muted">dBm</span></Row>
      <Row k="Origem do dado"><SourceChip p={o.provenance} /></Row>
    </dl><p className="mt-2 text-xs text-muted">Leitura observada na OLT, não uma medição de agora. Sem classificação de qualidade além da fonte disponível.</p></Card>
  );
  if (tab === "cpe") return (
    <Card title="Roteador (CPE)" testid="sub-cpe">
      {o.cpe.link === "confirmed" && o.cpe.device ? (
        <dl>
          <Row k="Equipamento">{o.cpe.device.vendor ?? "—"} {o.cpe.device.model ?? ""}{o.cpe.device.firmware ? ` · ${o.cpe.device.firmware}` : ""}</Row>
          <Row k="Gerência">{o.cpe.device.protocols.length ? o.cpe.device.protocols.join(", ").toUpperCase() : "—"}</Row>
          {o.cpe.provenance && <Row k="Origem do dado"><SourceChip p={o.cpe.provenance} /></Row>}
        </dl>
      ) : o.cpe.link === "suggested" ? (
        <p className="text-sm">Há {o.cpe.pending_suggestions} sugestão(ões) de roteador para esta ONU (indício, não prova). <Link href={`/rede/onu/${o.id}`} className="text-accent underline underline-offset-2">Revisar na ONU 360</Link></p>
      ) : o.cpe.link === "unavailable" ? <p className="text-sm text-muted">O vínculo ONU↔CPE está desligado para este provedor.</p>
        : <p className="text-sm text-muted">Nenhum roteador vinculado a esta ONU.</p>}
    </Card>
  );
  if (tab === "acoes") return (
    <Card title="Ações" testid="sub-acoes">
      <p className="text-sm">Nenhuma ação de escrita está liberada.</p>
      <p className="mt-1 text-sm text-muted">Reinício, troca de Wi-Fi e outras escritas ficam bloqueadas: operação ainda não homologada.</p>
      <Link href="/operacoes" className="mt-3 inline-flex min-h-touch items-center text-accent underline underline-offset-2">Ver Operações</Link>
    </Card>
  );
  const stale = o.provenance.quality === "stale";
  return (
    <div className="grid items-start gap-4 md:grid-cols-2">
      <Card title="Conexão" testid="sub-conexao">
        <p className="mb-3 flex items-center gap-2 text-lg font-semibold" data-testid="sub-state">
          {stale && <span className="text-sm font-normal text-warn">Último estado conhecido:</span>}<StatusPill value={o.status} /><span className="sr-only">{STATE[o.status] ?? o.status}</span>
        </p>
        <dl>
          <Row k="ONU aprovada"><span className="font-mono">{o.serial}</span></Row>
          <Row k="OLT · PON">{o.olt}{o.pon_path ? ` · ${o.pon_path}` : ""}</Row>
          <Row k="Origem do dado"><SourceChip p={o.provenance} /></Row>
        </dl>
        {stale && <p className="mt-2 text-sm text-warn">A idade do dado não indica que a ONU esteja offline.</p>}
        <Link href={`/rede/onu/${o.id}`} className="mt-2 inline-flex min-h-touch items-center text-sm text-accent underline underline-offset-2">Abrir ONU 360</Link>
      </Card>
      <div className="grid gap-4">
        <Card title="Roteador associado" testid="sub-cpe-summary">
          <p className="text-sm font-medium">{o.cpe.link === "confirmed" ? "Vínculo confirmado por uma pessoa" : o.cpe.link === "suggested" ? "Sugestão (indício, não prova)" : o.cpe.link === "unavailable" ? "Vínculo ONU↔CPE desligado para este provedor" : "Nenhum roteador vinculado"}</p>
          {o.cpe.device && <p className="mt-1 text-sm text-muted">{o.cpe.device.vendor ?? "—"} {o.cpe.device.model ?? ""}</p>}
        </Card>
        <Card title="Incidentes" testid="sub-incident">
          <p className="text-sm">{o.incident ? <><span className="text-danger">{cause[o.incident.suspected_cause] ?? cause.unknown}.</span> Não é diagnóstico.</> : o.incident_hidden ? "Seu papel não permite ver incidentes." : "Nenhum incidente registrado nesta observação."}</p>
        </Card>
      </div>
    </div>
  );
}

export default async function Subscriber360({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ aba?: string; onu?: string }> }) {
  const { id } = await params;
  const q = await searchParams;
  if (!UUID.test(id) || !(await subscriber360On())) notFound();  // desligada = a tela não existe para este provedor
  const r = await apiSafe<CustomerContext>(`/v1/customers/${id}/context`);
  if (r.status === 404) notFound();
  const shell = (c: React.ReactNode) => <AppShell active="/assinantes" user="1">{c}</AppShell>;
  if (r.status === 403) return shell(<ErrorState title="Sem permissão (403)" hint="Seu papel não permite acessar este assinante. Nenhum dado pessoal ou de conexão é exibido." />);
  if (!r.data) return shell(<ErrorState title="Não foi possível carregar a Visão 360" hint="Nenhuma informação sobre a conexão pode ser afirmada enquanto as fontes não responderem. Recarregue a página." />);
  const d = r.data;
  const o = d.onus.find((x) => x.id === q.onu) ?? d.onus[0];
  const tabs = tabsFor(o);
  const cur = tabs.some(([t]) => t === q.aba) ? (q.aba as string) : tabs[0][0];
  const ov = OVERALL[d.status];
  const diag = await diagnosticsOn();
  return shell(
    <>
      <PageHeader title={d.customer.display_name} subtitle="Visão 360 do assinante, com a origem de cada dado" helpSlug="assinantes/visao-360">
        {diag && o && <Link href={`/assinantes/diagnostico/${id}?onu=${o.id}`} data-testid="open-diagnostic" className="inline-flex min-h-touch items-center rounded-btn border border-line px-3 text-sm">Diagnóstico guiado</Link>}
        <Link href="/assinantes" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para Assinantes</Link>
      </PageHeader>
      <div data-testid="sub360-ready" className="grid gap-4">
        <section aria-label="Estado geral" data-testid="sub-overall" className="panel flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="flex items-start gap-3">
            <span aria-hidden className={`flex size-11 shrink-0 items-center justify-center rounded-2xl text-lg ${TONE[d.status]}`}>{ov.icon}</span>
            <div><p className="text-xs text-muted">Cobertura das informações</p><h2 className="text-xl font-semibold">{ov.label}</h2><p className="mt-1 max-w-2xl text-sm text-muted">{ov.why}</p></div>
          </div>
          <div className="text-right text-sm"><p>{contract[d.customer.contract_status] ?? contract.unknown}{d.customer.document_last4 ? ` · documento final ${d.customer.document_last4}` : ""}</p><SourceChip p={d.customer.provenance} /></div>
        </section>
        {d.onus_truncated && <p role="status" className="text-sm text-warn" data-testid="sub-truncated">Este cliente tem mais ONUs do que a tela mostra; o estado nunca é “Completo” nesse caso.</p>}
        {!o ? <EmptyState title="Nenhuma ONU aprovada para este cliente" hint="Aprove o vínculo em Assinantes para ver a conexão." /> : (
          <>
            {d.onus.length > 1 && (
              <nav aria-label="ONUs do cliente" className="flex flex-wrap gap-2" data-testid="sub-onus">
                {d.onus.map((x) => <a key={x.id} href={`?aba=${cur}&onu=${x.id}`} aria-current={x.id === o.id ? "true" : undefined}
                  className={`inline-flex min-h-touch items-center rounded-btn border px-3 font-mono text-sm ${x.id === o.id ? "border-accent bg-accent-soft" : "border-line"}`}>{x.serial}</a>)}
              </nav>
            )}
            <nav aria-label="Abas" className="flex flex-wrap gap-1 border-b border-line pb-2">
              {tabs.map(([t, label]) => <Tab key={t} id={t} cur={cur} onu={o.id}>{label}</Tab>)}
            </nav>
            {cur === "cliente" ? (
              <Card title="Cliente" testid="sub-cliente"><dl>
                <Row k="Nome">{d.customer.display_name}</Row>
                {d.customer.document_last4 && <Row k="Documento">final {d.customer.document_last4}</Row>}
                <Row k="Situação">{contract[d.customer.contract_status] ?? contract.unknown}</Row>
                <Row k="Origem do dado"><SourceChip p={d.customer.provenance} /></Row>
              </dl><p className="mt-3 text-xs text-muted">O acesso a dados de assinante fica registrado na auditoria.</p></Card>
            ) : <Panel tab={cur} o={o} />}
          </>
        )}
        <p className="text-xs text-muted">Wi-Fi e Histórico ainda não têm fonte homologada e por isso não aparecem aqui.</p>
      </div>
    </>,
  );
}
