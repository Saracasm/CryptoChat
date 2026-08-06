import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = process.env.FASTAPI_URL;

// POST /api/conversations/{id}/custom-chart -> "Make your own graph":
// run user- or AI-written pandas/plotly code, sandboxed on the backend
// (see app/sandbox.py), against the authenticated profile's own data.
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const profileId = request.headers.get("X-Profile-Id") ?? "";
  const body = await request.json();

  const res = await fetch(`${FASTAPI_URL}/conversations/${id}/custom-chart`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Profile-Id": profileId },
    body: JSON.stringify(body),
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
