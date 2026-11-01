import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { Card } from "@/components/Panel";
import { OpticalRuler } from "@/components/OpticalRuler";
import { PingTestSection } from "@/components/PingTestSection";
import { QualitySection } from "@/components/QualitySection";
import { SpeedTestSection } from "@/components/SpeedTestSection";
import { ago_, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import type { Onu360 } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TABS = [["resumo", "Resumo"], ["velocidade", "Velocidade"], ["qualidade", "Qualidade"], ["latencia", "Latência e DNS"]] as const;
type Tab = (typeof TABS)[number][0];

type Avail = { text: string; ok: boolean };
const NO_LINK: Avail = { text: "Indisponível: sem roteador vinculado", ok: false };
const FLAG_OFF: Avail = { text: "Indisponível: recurso desligado para este provedor", ok: false };

/** Diagnóstico da ONU (ADR-0037 emenda de 2026-11-01, ADR-0038, ADR-0039): reúne o sinal óptico e os testes que uma pessoa pode pedir. Nada inicia sozinho; cada teste que gera tráfego é pedido por quem tem permissão
 *  e aprovado por outra pessoa. A régua é referência de apresentação (G.984.2 classe B+), não homologada. */
export default async function DiagnosticoPage({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ aba?: string }> }) {
  const { id } = await params;
  const { aba } = await searchParams;
  if (!UUID.test(id)) notFound();
  const r = await apiSafe<Onu360>(`/v1/onus/${id}`);
  if (r.status === 404) notFound();
  if (r.status === 403) return <AppShell active="/rede" user="1"><ErrorState title="Sem permissão" hint="Seu papel não permite ver o inventário." /></AppShell>;
  const o = r.data;
  if (!o) return <AppShell active="/rede" user="1"><ErrorState title="Falha ao carregar a ONU" hint="Tente novamente em instantes." /></AppShell>;
  if (!(await featuresOn("onu_quick_inspector"))) notFound();   // a tela nova segue a flag da Rede: desligada, a rota não existe

  const linked = o.cpe?.link === "confirmed" && !!o.cpe.device;
  const cpeId = linked ? o.cpe!.device!.id : null;
  const [speedOn, qualityOn, pingOn] = linked
    ? await Promise.all([featuresOn("speed_diagnostics"), featuresOn("quality_diagnostics"), featuresOn("quality_active_tests")])
    : [false, false, false];
  const avail = (on: boolean): Avail => (!linked ? NO_LINK : !on ? FLAG_OFF : { text: "Disponível", ok: true });
  const tab: Tab = TABS.some(([k]) => k === aba) ? (aba as Tab) : "resumo";
  const href = (k: Tab) => `/rede/onu/${id}/diagnostico${k === "resumo" ? "" : `?aba=${k}`}`;
  const cards: { tab: Tab; title: string; what: string; a: Avail }[] = [
    { tab: "velocidade", title: "Velocidade", what: "Download e upload pela WAN de serviço (PPPoE) da ONT.", a: avail(speedOn) },
    { tab: "qualidade", title: "Qualidade da conexão", what: "Leitura rápida: óptica, WAN e Wi‑Fi, com o grau de confiança de cada sinal.", a: avail(qualityOn) },
    { tab: "latencia", title: "Ping e latência", what: "Latência mínima, média, máxima e perda até um destino do provedor.", a: avail(pingOn) },
    { tab: "latencia", title: "Jitter", what: "Variação da latência entre pacotes.", a: { text: "Indisponível: o aparelho não informa o tempo de cada pacote (só mínimo, média e máximo)", ok: false } },
    { tab: "latencia", title: "DNS", what: "Tempo de resolução de nomes.", a: { text: "Indisponível: os modelos de bancada não expõem o teste de DNS", ok: false } },
  ];

  return (
    <AppShell active="/rede" user="1">
      <PageHeader title="Diagnóstico" subtitle={`ONU ${o.serial} · ${o.olt.name}${o.pon?.path ? ` › PON ${o.pon.path}` : ""}`} helpSlug="rede/onu-360">
        <Link href={`/rede/onu/${id}`} className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline" data-testid="diag-back">← Voltar para a ONU</Link>
      </PageHeader>
      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm" data-testid="diag-header">
        <StatusPill value={o.status} />
        <span className="text-muted">{o.observed_at ? `Atualizado · ${ago_(o.observed_at)}` : "Sem coleta"}</span>
      </div>
      <div className="grid gap-4">
        <Card title="Sinal óptico" testid="diag-optical">
          <OpticalRuler rx={o.rx_dbm} freshness={o.freshness} agoText={o.observed_at ? ago_(o.observed_at) : null} size="lg" />
          <p className="mt-3 text-xs text-muted">Fonte: leitura da OLT{o.observed_at ? ` · ${ago_(o.observed_at)}` : ""}. A régua é uma referência de apresentação; a plataforma não julga o sinal.</p>
        </Card>
        <nav aria-label="Abas do diagnóstico" className="flex flex-wrap gap-1 border-b border-line" data-testid="diag-tabs">
          {TABS.map(([k, label]) => (
            <Link key={k} href={href(k)} aria-current={tab === k ? "page" : undefined} data-testid={`diag-tab-${k}`}
              className={`inline-flex min-h-touch items-center rounded-t-btn px-3 text-sm ${tab === k ? "border-b-2 border-accent font-semibold text-text" : "text-muted hover:text-text"}`}>{label}</Link>
          ))}
        </nav>
        {tab === "resumo" && (
          <section aria-label="Resumo dos testes" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="diag-summary">
            {cards.map((c) => (
              <Link key={c.title} href={href(c.tab)} className="panel grid gap-1 p-4 hover:border-accent" data-testid="diag-card">
                <span className="font-semibold">{c.title}</span>
                <span className="text-sm text-muted">{c.what}</span>
                <span className={`text-sm font-medium ${c.a.ok ? "text-ok" : "text-muted"}`}>{c.a.ok ? "✓ " : "— "}{c.a.text}</span>
              </Link>
            ))}
            <p className="text-xs text-muted sm:col-span-2 lg:col-span-3">Nada inicia sozinho: cada teste gera tráfego no aparelho e é pedido por uma pessoa com permissão; outra pessoa aprova em Operações.</p>
          </section>
        )}
        {tab === "velocidade" && (
          <Card title="Velocidade" testid="diag-speed">
            {cpeId && speedOn ? <SpeedTestSection key={cpeId} cpeId={cpeId} /> : <Unavailable a={avail(speedOn)} />}
          </Card>
        )}
        {tab === "qualidade" && (
          <Card title="Qualidade da conexão" testid="diag-quality">
            {cpeId && qualityOn ? <QualitySection key={cpeId} cpeId={cpeId} /> : <Unavailable a={avail(qualityOn)} />}
          </Card>
        )}
        {tab === "latencia" && (
          <div className="grid gap-4" data-testid="diag-latency">
            <Card title="Ping e latência" testid="diag-ping">
              {cpeId && pingOn ? <PingTestSection key={cpeId} cpeId={cpeId} /> : <Unavailable a={avail(pingOn)} />}
            </Card>
            <Card title="Jitter e DNS" testid="diag-jitter-dns">
              <ul className="grid gap-2 text-sm">
                <li><span className="font-medium">Jitter:</span> <span className="text-muted">ainda não disponível. O aparelho informa só mínimo, média e máximo; a tela mostra a amplitude (máx − mín), que não é jitter.</span></li>
                <li><span className="font-medium">DNS:</span> <span className="text-muted">ainda não disponível. Os modelos de bancada não expõem o teste de DNS; o ping até o servidor DNS do provedor mede alcance e latência, não a resolução de nomes.</span></li>
              </ul>
            </Card>
          </div>
        )}
      </div>
    </AppShell>
  );
}

function Unavailable({ a }: { a: Avail }) {
  return <p className="text-sm text-muted" data-testid="diag-unavailable">{a.text}.</p>;
}
