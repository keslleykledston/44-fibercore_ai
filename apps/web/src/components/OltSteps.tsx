import { OltConnectionDelivery } from "@/components/OltConnectionDelivery";
import { OltReadiness } from "@/components/OltReadiness";
import type { FleetOlt } from "@/lib/fleet";
import { HOST_KEY_HELP, stageText, TELNET_WARNING, TRUST_COMMAND } from "@/lib/oltConnection";
import { codeText, STATUS_PT, type Delivery, type SealKey } from "@/lib/oltSecrets";

type Step = { n: number; title: string; state: string; tone: "ok" | "wait" | "error" | "off"; body: React.ReactNode };
const toneCls = { ok: "text-ok", wait: "text-accent", error: "text-danger", off: "text-muted" } as const;
const toneMark = { ok: "✓", wait: "●", error: "▲", off: "○" } as const;

function latest(items: Delivery[], kind: string): Delivery | undefined {
  return items.find((d) => d.kind === kind);   // a API devolve da mais nova para a mais antiga
}
/** Estado de UMA entrega (o último envio daquele tipo) em português, com o motivo da falha. */
function deliveryState(d: Delivery | undefined): { text: string; tone: Step["tone"] } {
  if (!d) return { text: "Ainda não enviada", tone: "off" };
  const t = d.status === "FAILED" ? "error" : d.status === "APPLIED" ? "ok" : d.status === "PENDING" || d.status === "DISPATCHED" ? "wait" : "error";
  return { text: STATUS_PT[d.status] ?? d.status, tone: t };
}

/**
 * Assistente de cadastro (ADR-0046 D3): os quatro passos de uma OLT, cada um com o seu estado e o seu erro em português, e o reenvio de cada um sem refazer os outros:
 * 1 Cadastrar (nuvem) → 2 Entregar a conexão (cifrada, pelo mesmo canal das credenciais) → 3 Entregar credenciais (cartão abaixo) → 4 Testar conexão (leitura somente leitura).
 * Componente de servidor; o único trecho de cliente é o do passo 2 (selagem no navegador).
 */
export function OltSteps({ olt, secretsOn, deliveries, sealKey, edgeOk }: { olt: FleetOlt; secretsOn: boolean; deliveries: Delivery[] | null; sealKey: SealKey | null; edgeOk: boolean }) {
  const c = olt.connection, r = olt.readiness;
  const telnet = c.protocol === "telnet", simple = c.protocol === null;
  const items = deliveries ?? [];
  const conn = latest(items, "olt_connection");
  const keyConfirmed = sealKey?.state === "confirmed";
  const blocked = (why: string): Pick<Step, "state" | "tone" | "body"> => ({ state: telnet ? "Aguardando suporte a Telnet" : "Indisponível", tone: "off", body: <p className="text-xs text-muted">{why}</p> });
  const steps: Step[] = [];

  // 1 Cadastro
  steps.push({
    n: 1, title: "Cadastrar", state: "Feito", tone: "ok",
    body: (
      <>
        <p className="text-sm">Cadastrada na nuvem{olt.registered ? "" : " (criada pela primeira coleta do Edge)"}.
          {simple ? " Protocolo não informado: escolha SSH ou Telnet em " : " " + (c.protocol ?? "").toUpperCase() + `, porta ${c.port ?? "—"}. Para mudar, edite em `}
          <a href="#cadastro" className="text-accent underline underline-offset-2">Cadastro</a>.</p>
        {!simple && !telnet && !c.host_key_sha256 && <p className="mt-1 text-xs text-danger" data-testid="passo-sem-impressao">Falta a impressão digital do host SSH. Obtenha-a na rede da OLT com <code>{HOST_KEY_HELP}</code> e salve em Cadastro.</p>}
      </>
    ),
  });

  // 2 Conexão
  if (simple) steps.push({ n: 2, title: "Entregar a conexão", ...blocked("Escolha o protocolo (SSH) em Cadastro para entregar a conexão ao Edge.") });
  else if (telnet) steps.push({ n: 2, title: "Entregar a conexão", ...blocked("Aguardando suporte a Telnet: Telnet é só cadastro, nenhuma conexão é entregue ao Edge.") });
  else {
    const d = deliveryState(conn);
    let state = d.text, tone = d.tone;
    if (c.applied && c.trust_state === "trusted") { state = "Conexão aplicada e confirmada no Edge"; tone = "ok"; }
    else if (c.applied && c.trust_state === "awaiting_local_trust") { state = "Conexão aplicada: aguardando confirmação no Edge"; tone = "wait"; }
    else if (c.applied) { state = "Conexão aplicada (o Edge ainda não informou a confiança)"; tone = "wait"; }
    else if (conn?.status === "APPLIED") { state = "A conexão mudou depois da entrega: envie de novo"; tone = "error"; }
    steps.push({
      n: 2, title: "Entregar a conexão", state, tone,
      body: !edgeOk || !sealKey ? <p className="text-sm text-muted">O estado da chave do Edge não está disponível agora (recurso desligado, papel sem permissão ou o Edge ainda não publicou a chave).</p>
        : <OltConnectionDelivery olt={{ id: olt.id, name: olt.name, vendor: olt.vendor, edgeId: olt.edge.id, masked: olt.mgmt_address_masked, connection: c }} keyConfirmed={keyConfirmed} initialItems={items} />,
    });
  }

  // 3 Credenciais
  if (telnet) steps.push({ n: 3, title: "Entregar credenciais", ...blocked("Aguardando suporte a Telnet: nenhuma senha nem community é pedida ou entregue.") });
  else if (!secretsOn) steps.push({ n: 3, title: "Entregar credenciais", ...blocked("O recurso Credenciais da OLT (fleet_secrets) está desligado para este provedor.") });
  else if (simple) steps.push({ n: 3, title: "Entregar credenciais", ...blocked("Disponível depois de escolher o protocolo em Cadastro.") });
  else {
    const kind = c.transport === "snmp" ? "snmp_community" : "ssh_login";
    const d = deliveryState(latest(items, kind));
    const done = r.steps.credential;
    steps.push({
      n: 3, title: "Entregar credenciais", state: done ? "Credencial aplicada" : d.text, tone: done ? "ok" : d.tone,
      body: (
        <>
          <p className="text-sm">{c.transport === "snmp" ? "Community SNMP v2c" : "Login e senha (SSH)"}: o envio cifrado fica no cartão <a href="#credenciais" className="text-accent underline underline-offset-2">Credenciais da OLT</a>, abaixo. Pode ser reenviado a qualquer momento sem refazer os outros passos.</p>
          {codeText(latest(items, kind)?.code ?? null) && latest(items, kind)?.status === "FAILED" && <p className="mt-1 text-xs text-danger" data-testid="passo-credencial-erro">{codeText(latest(items, kind)?.code ?? null)}</p>}
          {c.applied && c.trust_state !== "trusted" && <p className="mt-1 text-xs text-muted">O Edge guarda a credencial, mas só a usa depois de confirmar o host no servidor dele.</p>}
        </>
      ),
    });
  }

  // 4 Teste
  if (telnet || simple) steps.push({ n: 4, title: "Testar conexão", ...blocked(telnet ? "Aguardando suporte a Telnet." : "Disponível depois de escolher o protocolo em Cadastro.") });
  else {
    const ready = c.trust_state === "trusted" && r.steps.credential;
    steps.push({
      n: 4, title: "Testar conexão", state: r.steps.tested ? "Testada" : ready ? "Pronta para testar" : "Ainda não testada", tone: r.steps.tested ? "ok" : ready ? "wait" : "off",
      body: (
        <>
          <p className="text-sm">O teste é só leitura (modelo e firmware). Resultado e limite no cartão <a href="#teste" className="text-accent underline underline-offset-2">Teste de conexão</a>.{!ready && " O Edge só conecta depois da confirmação do host e com a credencial aplicada."}</p>
          <form method="post" action={`/bff/frota/olts/${olt.id}/testar`} className="mt-2"><button type="submit" data-testid="passo-testar" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg">Testar conexão</button></form>
        </>
      ),
    });
  }

  return (
    <section id="passos" className="panel p-3 md:col-span-2" aria-label="Assistente de cadastro" data-testid="frota-passos">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">Assistente de cadastro</h2>
      <div className="mb-2 grid gap-1"><p className="text-sm">Prontidão: <strong data-testid="frota-prontidao-texto">{stageText(r)}</strong></p><OltReadiness r={r} testId="frota-prontidao-detalhe" /></div>
      {c.applied && c.trust_state === "awaiting_local_trust" && (
        <p className="mb-3 rounded-btn border border-accent px-3 py-2 text-sm" data-testid="passos-comando">Aguardando confirmação no Edge. No servidor do Edge rode: <code className="select-all break-all font-mono text-xs">{TRUST_COMMAND(olt.name)}</code></p>
      )}
      {telnet && <p role="note" className="mb-3 rounded-btn border border-line px-3 py-2 text-sm" data-testid="passos-telnet">{TELNET_WARNING}</p>}
      <ol className="grid gap-2">
        {steps.map((s) => (
          <li key={s.n} data-testid={`passo-${s.n}`} className="rounded-btn border border-line px-3 py-2">
            <h3 className="mb-1 flex flex-wrap items-baseline gap-x-3 text-sm font-semibold"><span>{s.n}. {s.title}</span>
              <span className={`text-xs font-medium ${toneCls[s.tone]}`} data-testid="passo-estado"><span aria-hidden>{toneMark[s.tone]} </span>{s.state}</span></h3>
            {s.body}
          </li>))}
      </ol>
    </section>
  );
}
