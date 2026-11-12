import { apiSafe } from "@/lib/api";
import { OltCredentials, FingerprintCheck } from "@/components/OltCredentials";
import { EDGE_ADMIN_NOTE, type Delivery, type SealKey } from "@/lib/oltSecrets";
import type { FleetOlt } from "@/lib/fleet";

/**
 * Cartão "Credenciais da OLT" (ADR-0045). Componente de servidor: mostra o estado e a impressão digital da chave do Edge, o formulário de confirmação (POST simples ao BFF, funciona sem JavaScript) e,
 * só com o recurso ligado e a chave confirmada, o formulário de envio cifrado (componente de cliente: exige JavaScript e WebCrypto).
 * Flags `fleet_secrets` e `fleet_provision` desligadas (ou papel sem as permissões) ⇒ a API responde 403 e o cartão não existe (retorna null): nada é mostrado nem perguntado.
 * ADR-0046: com SÓ a `fleet_provision` ligada o cartão mostra apenas a chave do Edge (confirmar é necessário para entregar a conexão) e nenhum campo de credencial; Telnet nunca mostra campo de senha/community.
 */
export async function OltCredentialsCard({ olt, secretsOn = true }: { olt: FleetOlt; secretsOn?: boolean }) {
  const key = await apiSafe<SealKey>(`/v1/fleet/edges/${olt.edge.id}/seal-key`);
  if (!key.data) return null;   // 403 (flag desligada ou papel sem permissão), 404 ou falha: cartão ausente
  const k = key.data;
  const telnet = olt.connection.protocol === "telnet";
  const list = secretsOn && !telnet ? await apiSafe<{ items: Delivery[] }>(`/v1/fleet/olts/${olt.id}/secret-deliveries`) : { data: null };
  const confirmed = k.state === "confirmed";
  return (
    <section id="credenciais" className="panel p-4 md:col-span-2" aria-label="Credenciais da OLT" data-testid="frota-credenciais">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">{secretsOn ? "Credenciais da OLT" : "Chave do Edge"}</h2>
      {secretsOn && !telnet && <div className="mb-4 grid gap-1 text-sm text-muted">
        <p>Login, senha e community SNMP são <strong>cifrados no seu navegador</strong> com a chave pública do Edge e só o Edge consegue abri-los: a nuvem, o servidor web e os backups guardam apenas texto cifrado, e nada devolve o segredo. A tela nunca mostra o que foi enviado.</p>
        <ul className="list-disc pl-5" data-testid="cred-avisos">
          <li>Depois que o Edge aplicar, use <strong>Testar conexão</strong> (acima) para conferir se o novo login funciona.</li>
          <li>SNMP v3 não é suportado: só a community v2c é enviada.</li>
          <li>{EDGE_ADMIN_NOTE}</li>
          <li>Isto não troca a senha na OLT: só atualiza a cópia que o Edge usa.</li>
        </ul>
      </div>}
      {telnet && <p role="note" className="mb-4 text-sm text-muted" data-testid="cred-telnet">Telnet é só cadastro: nenhuma senha nem community é pedida ou entregue ao Edge para esta OLT (aguardando suporte a Telnet).</p>}
      <div className="grid gap-4 md:grid-cols-2">
        <div data-testid="cred-chave" className="grid content-start gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Chave do Edge “{k.edge_name}”</h3>
          {k.state === "none" || !k.public_key || !k.key_id || !k.fingerprint ? (
            <p className="text-sm" data-testid="cred-chave-estado">O Edge ainda não publicou a chave de selagem. Atualize o Edge para a versão que a publica e aguarde o próximo ciclo; depois atualize esta página.</p>
          ) : (
            <>
              <p className="text-sm" data-testid="cred-chave-estado">{confirmed ? `Confirmada${k.confirmed_at ? ` em ${new Date(k.confirmed_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}` : ""}.` : "Aguardando a sua confirmação. Enquanto não for confirmada nenhuma credencial pode ser enviada."}</p>
              <p className="text-sm">Impressão digital: <span className="font-mono text-base" data-testid="cred-fingerprint">{k.fingerprint}</span></p>
              <FingerprintCheck publicKey={k.public_key} serverFingerprint={k.fingerprint} />
              {!confirmed && (
                <form method="post" action={`/bff/frota/edges/${olt.edge.id}/chave/confirmar`} className="grid gap-2" data-testid="cred-confirmar">
                  <input type="hidden" name="key_id" value={k.key_id} />
                  <input type="hidden" name="olt" value={olt.id} />
                  <p className="text-sm" data-testid="cred-confirmar-contexto">Confira no servidor do Edge <strong>“{k.edge_name}”</strong> (é o Edge da OLT “{olt.name}”): a chave é do Edge, vale para todas as OLTs dele.</p>
                  <label className="grid gap-1 text-sm">Digite a impressão digital mostrada no servidor do Edge
                    <input name="fingerprint" required maxLength={64} autoComplete="off" spellCheck={false} placeholder="xxxx-xxxx-xxxx-xxxx-xxxx-xxxx-xxxx-xxxx" className="min-h-touch rounded-btn border border-line bg-bg px-3 font-mono" /></label>
                  <p className="text-xs text-muted">No servidor do Edge rode <code>fibercore-edge seal-fingerprint</code> e compare <strong>digitando</strong> o valor que ele mostra (não copie desta tela): assim você confirma que a chave que vamos usar é a do seu Edge.</p>
                  <div><button type="submit" data-testid="cred-confirmar-btn" className="min-h-touch rounded-btn border border-line px-4 text-sm hover:bg-bg">Confirmar chave</button></div>
                </form>
              )}
            </>
          )}
        </div>
        {secretsOn && !telnet && <div data-testid="cred-envio" className="grid content-start gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Enviar credenciais</h3>
          {confirmed ? <OltCredentials oltId={olt.id} oltName={olt.name} edgeId={olt.edge.id} snmpV3={olt.snmp_version === "v3"} initialItems={list.data?.items ?? []} keyConfirmed />
            : <p className="text-sm text-muted" data-testid="cred-bloqueado">Disponível depois que a chave do Edge for confirmada.</p>}
        </div>}
      </div>
    </section>
  );
}
