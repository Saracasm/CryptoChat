import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = process.env.FASTAPI_URL;

// GET /api/documents -> list the acting profile's uploaded documents
export async function GET(request: NextRequest) {
  const authHeader = request.headers.get("Authorization") ?? "";
  const res = await fetch(`${FASTAPI_URL}/documents`, {
    headers: { Authorization: authHeader },
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

// POST /api/documents -> upload + ingest one file into the acting profile's
// private RAG corpus. The incoming multipart body is forwarded as-is.
export async function POST(request: NextRequest) {
  const authHeader = request.headers.get("Authorization") ?? "";
  const formData = await request.formData();

  const res = await fetch(`${FASTAPI_URL}/documents/upload`, {
    method: "POST",
    headers: { Authorization: authHeader },
    body: formData,
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
