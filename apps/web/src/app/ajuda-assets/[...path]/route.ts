import fs from "node:fs";
import { NextResponse } from "next/server";
import { assetPath } from "@/lib/help";
import { getSession } from "@/lib/session";

export async function GET(_req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  if (!(await getSession()).token) return new NextResponse("unauthorized", { status: 401 });
  const file = assetPath((await params).path);
  if (!file) return new NextResponse("not found", { status: 404 });
  return new NextResponse(fs.readFileSync(file), { headers: { "content-type": "image/png", "cache-control": "private, max-age=300", "x-content-type-options": "nosniff" } });
}
