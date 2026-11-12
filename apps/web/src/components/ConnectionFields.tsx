"use client";
import { useId, useState } from "react";
import { DEFAULT_PORT, defaultPortFor, HOST_KEY_HELP, PROTOCOLS, SSH_MODES, TELNET_WARNING, TRANSPORTS } from "@/lib/oltConnection";

type Defaults = { protocol: string | null; port: number | null; transport: string | null; snmp_port: number | null; host_key_sha256: string | null; ssh_mode: string | null; legacy_ssh: boolean };
const field = "min-h-touch rounded-btn border border-line bg-bg px-3";

/**
 * Como a OLT é alcançada (ADR-0046 D3): protocolo, porta (o preset acompanha o protocolo), transporte da coleta, porta SNMP, impressão digital do host SSH, modo SSH e SSH legado.
 * Nada aqui é secreto. Telnet é só inventário: esconde impressão digital, modo e SSH legado e mostra o aviso. Os campos têm `name`: funcionam num envio nativo (sem JavaScript) e no cadastro com JavaScript.
 * `mgmt_port_original` leva a porta que a OLT tinha, para o servidor só enviar a porta se ela mudou (assim trocar o protocolo usa a porta padrão do novo protocolo).
 */
export function ConnectionFields({ defaults }: { defaults: Defaults }) {
  const base = useId();
  const [protocol, setProtocol] = useState(defaults.protocol ?? "");
  const [port, setPort] = useState(defaults.port !== null ? String(defaults.port) : "");
  const [transport, setTransport] = useState(defaults.transport ?? "cli");
  const id = (s: string) => `${base}-${s}`;
  function onProtocol(next: string) {
    const prevDefault = defaultPortFor(protocol);
    if (port === "" || (prevDefault !== null && port === String(prevDefault))) setPort(defaultPortFor(next) !== null ? String(DEFAULT_PORT[next]) : "");   // o preset acompanha o protocolo enquanto a porta é a padrão do anterior
    setProtocol(next);
  }
  const ssh = protocol === "ssh";
  return (
    <fieldset className="grid gap-3 md:col-span-2 md:grid-cols-2" data-testid="frota-conexao">
      <legend className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Como a OLT é alcançada (nada aqui é secreto)</legend>
      <label className="grid gap-1 text-sm" htmlFor={id("proto")}>Protocolo de acesso
        <select id={id("proto")} name="mgmt_protocol" value={protocol} onChange={(e) => onProtocol(e.target.value)} className={field}>
          <option value="">Não informar (cadastro simples)</option>{PROTOCOLS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
      <label className="grid gap-1 text-sm" htmlFor={id("port")}>Porta de acesso
        <input id={id("port")} name="mgmt_port" value={port} onChange={(e) => setPort(e.target.value)} inputMode="numeric" pattern="[0-9]*" maxLength={5} autoComplete="off" disabled={!protocol} className={`${field} font-mono`} placeholder={protocol ? String(defaultPortFor(protocol)) : "escolha o protocolo"} />
        <span className="text-xs text-muted">Padrão: SSH 22, Telnet 23 (1 a 65535).</span></label>
      <input type="hidden" name="mgmt_port_original" value={defaults.port ?? ""} />
      {protocol === "telnet" && <p role="note" data-testid="frota-telnet-aviso" className="rounded-btn border border-line px-3 py-2 text-sm md:col-span-2">{TELNET_WARNING}</p>}
      {ssh && (
        <>
          <label className="grid gap-1 text-sm" htmlFor={id("transp")}>Transporte da coleta
            <select id={id("transp")} name="mgmt_transport" value={transport} onChange={(e) => setTransport(e.target.value)} className={field}>{TRANSPORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
            <span className="text-xs text-muted">SNMP exige a versão SNMP v2c (campo acima).</span></label>
          <label className="grid gap-1 text-sm" htmlFor={id("snmpport")}>Porta SNMP
            <input id={id("snmpport")} name="snmp_port" defaultValue={defaults.snmp_port ?? ""} inputMode="numeric" pattern="[0-9]*" maxLength={5} autoComplete="off" className={`${field} font-mono`} placeholder="161" /></label>
          <label className="grid gap-1 text-sm md:col-span-2" htmlFor={id("hk")}>Impressão digital do host SSH
            <input id={id("hk")} name="host_key_sha256" defaultValue={defaults.host_key_sha256 ?? ""} maxLength={64} autoComplete="off" spellCheck={false} className={`${field} font-mono`} placeholder="SHA256:…" />
            <span className="text-xs text-muted">Obtenha na rede da OLT com <code>{HOST_KEY_HELP}</code> (troque IP pelo endereço da OLT; confira por um canal confiável). A nuvem só a repassa ao Edge, que NÃO conecta antes de quem administra o Edge confirmá-la no servidor dele.</span></label>
          <label className="grid gap-1 text-sm" htmlFor={id("mode")}>Modo SSH
            <select id={id("mode")} name="ssh_mode" defaultValue={defaults.ssh_mode ?? "exec"} className={field}>{SSH_MODES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label className="flex min-h-touch items-center gap-2 text-sm" htmlFor={id("legacy")}>
            <input id={id("legacy")} type="checkbox" name="legacy_ssh" value="1" defaultChecked={defaults.legacy_ssh} className="h-6 w-6" /> SSH legado (algoritmos antigos; o Edge só aceita se a política local permitir)</label>
        </>
      )}
    </fieldset>
  );
}
