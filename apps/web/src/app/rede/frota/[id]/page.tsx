import Link from "next/link";
import { notFound } from "next/navigation";
import { AppShell } from "@/components/AppShell";
import { DeviceThumb } from "@/components/DeviceThumb";
import { DataFreshness, ErrorState, PageHeader, StatusPill } from "@/components/ui";
import { apiSafe } from "@/lib/api";
import { featuresOn } from "@/lib/features";
import { FormHelp } from "@/components/FormHelp";
import { PopCombobox } from "@/components/PopCombobox";
import { ConnectionFields } from "@/components/ConnectionFields";
import { OltCredentialsCard } from "@/components/OltCredentialsCard";
import { OltReadiness } from "@/components/OltReadiness";
import { OltSteps } from "@/components/OltSteps";
import { ADDRESS_HELP, CRED_HELP, FLEET_FLASH, JOB_LABEL, SNMP_VERSIONS, UUID, uptimeText, type ConnectionTests, type FleetOlt, type Pop } from "@/lib/fleet";
import type { Delivery, SealKey } from "@/lib/oltSecrets";

const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

export default async function FrotaOlt({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ ok?: string | string[]; erro?: string | string[] }> }) {
  if (!(await featuresOn("fleet_manager"))) notFound();
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
  const ok = one(sp.ok), erro = one(sp.erro);
  const [r, pops, assets, tests, secretsOn, provisionOn] = await Promise.all([apiSafe<FleetOlt>(`/v1/fleet/olts/${id}`), apiSafe<{ items: Pop[] }>("/v1/pops"), featuresOn("device_assets"), apiSafe<ConnectionTests>(`/v1/fleet/olts/${id}/connection-tests`), featuresOn("fleet_secrets"), featuresOn("fleet_provision")]);
  if (r.status === 404) notFound();
  const shell = (c: React.ReactNode) => <AppShell active="/rede" user="1">{c}</AppShell>;
  if (r.status === 403) return shell(<ErrorState title="Sem permissão" hint="Seu papel não permite ver esta OLT." />);
  if (!r.data) return shell(<ErrorState title="Não foi possível carregar a OLT" hint="Recarregue a página." />);
  const o = r.data;
  // ADR-0046: o assistente de cadastro precisa da chave do Edge e das entregas (a API só responde com a permissão e uma das duas flags; senão o assistente não aparece)
  const [sealKey, deliveries] = provisionOn ? await Promise.all([apiSafe<SealKey>(`/v1/fleet/edges/${o.edge.id}/seal-key`), apiSafe<{ items: Delivery[] }>(`/v1/fleet/olts/${id}/secret-deliveries`)]) : [null, null];
  const msg = ok && FLEET_FLASH[ok] ? FLEET_FLASH[ok] : erro && FLEET_FLASH[erro] ? FLEET_FLASH[erro] : null;
  return shell(
    <>
      <PageHeader title={o.name} subtitle="Cadastro e identificação da OLT. Somente leitura." helpSlug="rede/frota-de-olts">
        <Link href="/rede/frota" className="inline-flex min-h-touch items-center rounded-btn px-3 text-sm text-accent hover:underline">← Voltar para a Frota</Link>
      </PageHeader>
      {msg && <p role={erro ? "alert" : "status"} data-testid="frota-flash" className={`mb-4 rounded-btn border px-3 py-2 text-sm ${erro ? "border-danger text-danger" : "border-ok text-ok"}`}>{msg}</p>}
      <div className="grid gap-4 md:grid-cols-2" data-testid="frota-detalhe">
        <section className="panel flex items-start gap-4 p-4 md:col-span-2" aria-label="Identificação">
          {assets && <DeviceThumb category="olt" vendor={o.vendor} model={o.model} width={72} label />}
          <dl className="grid flex-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div><dt className="text-xs text-muted">Fabricante · modelo</dt><dd>{o.vendor} {o.model ?? "— (ainda não lido pelo Edge)"}</dd></div>
            <div><dt className="text-xs text-muted">Firmware</dt><dd>{o.firmware ?? "—"}</dd></div>
            <div><dt className="text-xs text-muted">Nível do driver</dt><dd><StatusPill value={o.support_level} /></dd></div>
            <div><dt className="text-xs text-muted">Última coleta</dt><dd>{o.observed_at ? <DataFreshness freshness="fresh" observedAt={o.observed_at} /> : "Ainda não coletada"}</dd></div>
            <div><dt className="text-xs text-muted">Edge</dt><dd>{o.edge.name}</dd></div>
            <div><dt className="text-xs text-muted">Endereço de gerência · SNMP</dt><dd data-testid="frota-endereco">{o.mgmt_address_masked ?? "Não informado"} · {o.snmp_version ? `SNMP ${o.snmp_version}` : "SNMP não informado"}</dd></div>
            {o.connection.protocol && <div><dt className="text-xs text-muted">Acesso · prontidão</dt><dd data-testid="frota-acesso">{o.connection.protocol.toUpperCase()} · porta {o.connection.port ?? "—"}<div className="mt-1"><OltReadiness r={o.readiness} testId="frota-prontidao" /></div></dd></div>}
            <div><dt className="text-xs text-muted">Credencial</dt><dd data-testid="frota-credencial">{o.has_credential_ref ? "Informada" : "Não informada"}</dd></div>
            {o.collected && <div><dt className="text-xs text-muted">ONUs</dt><dd><Link href={`/rede?olt=${o.id}`} className="text-accent underline underline-offset-2">Ver as ONUs desta OLT</Link></dd></div>}
          </dl>
        </section>
        {provisionOn && sealKey?.data && <OltSteps olt={o} secretsOn={secretsOn} deliveries={deliveries?.data?.items ?? null} sealKey={sealKey.data} edgeOk />}
        <section id="cadastro" className="panel p-4 md:col-span-2" aria-label="Cadastro">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Cadastro</h2>
          <form method="post" action={`/bff/frota/olts/${o.id}`} className="grid gap-x-3 gap-y-2 md:grid-cols-6">
            <div className="md:col-span-2"><PopCombobox pops={(pops.data?.items ?? []).map((p) => ({ id: p.id, name: p.name }))} defaultName={o.pop?.name ?? ""} /></div>
            <label className="grid gap-1 text-sm md:col-span-2">Rótulo<input name="label" defaultValue={o.label ?? ""} maxLength={80} className={field} /></label>
            <label className="grid gap-1 text-sm md:col-span-2">Versão do SNMP<select name="snmp_version" defaultValue={o.snmp_version ?? ""} className={field}><option value="">Não informar</option>{SNMP_VERSIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
            <div className="grid content-start gap-1 md:col-span-3">
              <label className="grid gap-1 text-sm">{o.mgmt_address_masked ? "Substituir o endereço de gerência" : "Endereço de gerência"}<input name="mgmt_address" maxLength={45} autoComplete="off" spellCheck={false} className={`${field} font-mono`} placeholder={o.mgmt_address_masked ? "vazio = manter o atual" : "ex.: 10.20.30.40"} /></label>
              {o.mgmt_address_masked && <label className="flex items-center gap-2 text-xs text-muted"><input type="checkbox" name="remover_endereco" value="1" /> Remover o endereço</label>}
            </div>
            <div className="grid content-start gap-1 md:col-span-3">
              <label className="grid gap-1 text-sm">{o.has_credential_ref ? "Substituir o nome da credencial no Edge" : "Nome da credencial no Edge"}<input name="credential_ref" defaultValue="" maxLength={64} autoComplete="off" spellCheck={false} placeholder={o.has_credential_ref ? "vazio = manter a atual" : "ex.: olt-centro-01"} className={`${field} font-mono`} /></label>
              {o.has_credential_ref && <label className="flex items-center gap-2 text-xs text-muted"><input type="checkbox" name="remover_credencial" value="1" /> Remover o nome da credencial</label>}
            </div>
            <ConnectionFields defaults={{ protocol: o.connection.protocol, port: o.connection.port, transport: o.connection.transport, snmp_port: o.connection.snmp_port, host_key_sha256: o.connection.host_key_sha256, ssh_mode: o.connection.ssh_mode, legacy_ssh: o.connection.legacy_ssh }} />
            <FormHelp>
              <p><strong>Endereço.</strong> {ADDRESS_HELP} O endereço já salvo não é mostrado por inteiro.</p>
              <p><strong>Credencial.</strong> {CRED_HELP} O nome já informado não é mostrado de volta.</p>
            </FormHelp>
            <div className="md:col-span-6"><button type="submit" data-testid="frota-salvar" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg">Salvar</button></div>
          </form>
        </section>
        <section id="teste" className="panel p-4 md:col-span-2" aria-label="Teste de conexão" data-testid="frota-teste">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Teste de conexão</h2>
          <p className="mb-3 text-sm text-muted">Leitura de modelo e firmware pelo Edge na próxima janela de coleta (somente leitura). Limite: 1 teste a cada 15 minutos e 4 por hora por OLT.</p>
          {tests.data === null ? <p className="text-sm text-muted">O histórico de testes não está disponível agora.</p> : (
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <form method="post" action={`/bff/frota/olts/${o.id}/testar`} className="mb-3 flex flex-wrap items-center gap-3">
                  <button type="submit" data-testid="frota-testar" disabled={tests.data.budget.wait_seconds > 0} className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg disabled:opacity-60">Testar conexão</button>
                  <span data-testid="frota-orcamento" className="text-xs text-muted">{tests.data.budget.wait_seconds > 0 ? `Próximo teste em cerca de ${Math.ceil(tests.data.budget.wait_seconds / 60)} min. ` : ""}{tests.data.budget.used_last_hour} de {tests.data.budget.max_per_hour} na última hora.</span>
                </form>
                {tests.data.latest ? (
                  <dl className="grid gap-1 text-sm" data-testid="frota-identidade">
                    <div><dt className="text-xs text-muted">Lido pelo Edge há {Math.floor(tests.data.latest.age_seconds / 60)} min{tests.data.latest.stale ? " (leitura antiga)" : ""}</dt><dd className="font-medium">{tests.data.latest.identity.model} · {tests.data.latest.identity.firmware}</dd></div>
                    <div><dt className="text-xs text-muted">Patch · tempo ligada</dt><dd>{tests.data.latest.identity.patch ?? "não informado"} · {tests.data.latest.identity.uptime_seconds == null ? "não informado" : uptimeText(tests.data.latest.identity.uptime_seconds)}</dd></div>
                    <div><dt className="text-xs text-muted">Fabricante (o do cadastro; a leitura não o informa)</dt><dd>{tests.data.latest.identity.vendor}</dd></div>
                    <div data-testid="frota-confere" className={tests.data.latest.identity.matches_collected === false ? "text-danger" : "text-muted"}>
                      {tests.data.latest.identity.matches_collected === true ? "Confere com a identidade que a coleta já tinha." : tests.data.latest.identity.matches_collected === false ? "DIVERGE da identidade que a coleta já tinha: confira o cadastro e a configuração do Edge." : "Ainda não há coleta para comparar."}
                    </div>
                  </dl>
                ) : <p className="text-sm text-muted" data-testid="frota-sem-identidade">Nenhum teste concluído ainda.</p>}
              </div>
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Pedidos recentes</h3>
                {tests.data.items.length === 0 ? <p className="text-sm text-muted">Nenhum teste pedido.</p> : (
                  <ul className="divide-y divide-line text-sm" data-testid="frota-testes">{tests.data.items.map((t) => (
                    <li key={t.id} className="py-1.5"><span data-testid="volatile">{new Date(t.requested_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}</span> · {t.outcome === "cached" ? "Respondido do que já estava guardado" : `Pedido ao Edge: ${t.job_status ? JOB_LABEL[t.job_status] ?? t.job_status : "—"}`}</li>))}</ul>
                )}
                <p className="mt-2 text-xs"><Link href={`/rede/frota/${o.id}`} className="text-accent underline underline-offset-2">Atualizar</Link></p>
              </div>
            </div>
          )}
        </section>
        <OltCredentialsCard olt={o} secretsOn={secretsOn} />
      </div>
    </>,
  );
}
