// Entrega cifrada feita no NAVEGADOR (ADR-0045/0046): busca a chave pública do Edge, confere o key_id recalculado, sela o texto claro (conexão ou credencial) e o envia como texto cifrado.
// Usada pelo formulário único de cadastro. O texto claro nunca sai desta função em claro: só `sealed` vai para a rede; nenhuma mensagem de erro repete valor digitado.
import { SealError, keyIdOf, sealOltSecret, type Plain } from "@/lib/oltSeal";
import { SEND_ERR_PT, type SealKey } from "@/lib/oltSecrets";

export const SEAL_WINDOW_SECONDS = 1800;
export type KeyResult = { ok: true; key: SealKey } | { ok: false; unconfirmed: boolean; text: string };
export type SendResult = { ok: true } | { ok: false; text: string };

export function sealSupported(): boolean {
  return !!globalThis.isSecureContext && !!globalThis.crypto?.subtle && typeof globalThis.crypto.randomUUID === "function";
}

/** A chave vigente do Edge. `unconfirmed` = ainda falta confirmar a impressão digital (o envio fica para depois, sem erro de rede). */
export async function fetchSealKey(edgeId: string): Promise<KeyResult> {
  try {
    const kr = await fetch(`/bff/frota/edges/${edgeId}/chave`, { cache: "no-store", credentials: "same-origin" });
    if (!kr.ok) return { ok: false, unconfirmed: false, text: kr.status === 401 ? SEND_ERR_PT.unauthorized : kr.status === 403 ? SEND_ERR_PT.forbidden : SEND_ERR_PT.falha };
    const key = (await kr.json()) as SealKey;
    if (key.state !== "confirmed" || !key.public_key || !key.key_id || key.edge_id !== edgeId) return { ok: false, unconfirmed: true, text: SEND_ERR_PT.seal_key_not_confirmed };
    if ((await keyIdOf(key.public_key)) !== key.key_id) return { ok: false, unconfirmed: false, text: "A chave recebida não é consistente com o seu identificador. Nada foi enviado." };
    return { ok: true, key };
  } catch {
    return { ok: false, unconfirmed: false, text: SEND_ERR_PT.falha };
  }
}

/** Sela `plain` com a chave do Edge e o entrega à OLT `oltId`. `beforeSend` roda depois da selagem e antes da requisição (o chamador apaga os campos de texto claro ali). */
export async function sealAndDeliver(o: { oltId: string; oltName: string; key: SealKey; plain: Plain; beforeSend?: () => void }): Promise<SendResult> {
  try {
    const deliveryId = globalThis.crypto.randomUUID();
    const expiresAt = o.key.server_time + SEAL_WINDOW_SECONDS;   // o relógio da nuvem, não o do navegador
    const sealed = await sealOltSecret({ tenantId: o.key.tenant_id, edgeId: o.key.edge_id, oltName: o.oltName, deliveryId, keyId: o.key.key_id!, expiresAtUnix: expiresAt, edgePublicKey: o.key.public_key!, plain: o.plain });
    o.beforeSend?.();
    const r = await fetch(`/bff/frota/olts/${o.oltId}/credenciais`, {
      method: "POST", credentials: "same-origin", headers: { "content-type": "application/json" },
      body: JSON.stringify({ delivery_id: deliveryId, kind: o.plain.kind, key_id: o.key.key_id, expires_at: expiresAt, sealed: sealed.sealed }),
    });
    if (r.status === 202) return { ok: true };
    const d = ((await r.json().catch(() => null)) as { detail?: string } | null)?.detail ?? "";
    return { ok: false, text: SEND_ERR_PT[d] ?? SEND_ERR_PT.falha };
  } catch (e) {
    return { ok: false, text: e instanceof SealError ? e.message : SEND_ERR_PT.falha };   // só um SealError (sem o valor digitado) tem mensagem própria
  }
}
