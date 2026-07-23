import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = process.env.FASTAPI_URL;

// GET /api/conversations/{id}/messages -> load transcript
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const profileId = request.headers.get("X-Profile-Id") ?? "";

  const res = await fetch(`${FASTAPI_URL}/conversations/${id}/messages`, {
    headers: { "X-Profile-Id": profileId },
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

// POST /api/conversations/{id}/messages -> send a message
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const profileId = request.headers.get("X-Profile-Id") ?? "";
  const body = await request.json();

  const res = await fetch(`${FASTAPI_URL}/conversations/${id}/messages`, {
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
