import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = process.env.FASTAPI_URL;

// POST /api/conversations/{id}/portfolio-chart -> allocation/profit_loss/cost_vs_value chart
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const profileId = request.headers.get("X-Profile-Id") ?? "";
  const body = await request.json();

  const res = await fetch(`${FASTAPI_URL}/conversations/${id}/portfolio-chart`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Profile-Id": profileId,
    },
    body: JSON.stringify(body),
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
