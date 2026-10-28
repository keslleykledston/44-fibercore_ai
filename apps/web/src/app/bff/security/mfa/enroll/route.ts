import QRCode from "qrcode";
import { failure, forward, readFields, reply } from "@/lib/mfa-bff";

export async function POST(req: Request) {
  const f = await readFields(req, [{ name: "password", min: 1, max: 256 }]);
  if (f instanceof Response) return f;
  const r = await forward("/v1/auth/mfa/enroll", { password: f.password });
  const j = r.json as { secret?: string; otpauth_uri?: string } | null;
  if (r.status !== 200 || !j?.secret || !j.otpauth_uri) return failure(r.status, r.json);
  // QR gerado aqui, no servidor: o segredo viaja só nesta resposta (TLS, no-store) e nenhuma biblioteca de QR vai ao navegador.
  const qr = await QRCode.toDataURL(j.otpauth_uri, { errorCorrectionLevel: "M", margin: 2, width: 224 });
  return reply({ secret: j.secret, qr });
}
