import { NextResponse } from "next/server";
import { apiPost } from "@/lib/api";
import { back } from "@/lib/bff";
import { sameOrigin } from "@/lib/csrf";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function POST(req: Request, { params }: { params: Promise<{ id: string; action: string }> }) {
  if (!sameOrigin(req)) return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  const { id, action } = await params;
  const onu = new URL(req.url).searchParams.get("onu") ?? "";
  if (!UUID.test(id) || !UUID.test(onu) || !["confirm", "reject"].includes(action)) return NextResponse.json({ detail: "not found" }, { status: 404 });
  const r = await apiPost(`/v1/onu-cpe-links/${id}/${action}`);
  return back(req, `/rede/onu/${onu}?${r.status === 200 ? `cpe=${action}` : `cpe_erro=${r.status}`}`);
}
