import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = process.env.FASTAPI_URL;

// GET /api/conversations/{id}/messages -> load transcript
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const authHeader = request.headers.get("Authorization") ?? "";
  const res = await fetch(`${FASTAPI_URL}/conversations/${id}/messages`, {
    headers: { Authorization: authHeader },
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
  const authHeader = request.headers.get("Authorization") ?? "";
  const body = await request.json();
  const res = await fetch(`${FASTAPI_URL}/conversations/${id}/messages`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: authHeader,
    },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}