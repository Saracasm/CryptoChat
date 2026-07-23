import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = process.env.FASTAPI_URL;

export async function POST(request: NextRequest) {
  const profileId = request.headers.get("X-Profile-Id") ?? "";

  const res = await fetch(`${FASTAPI_URL}/conversations`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Profile-Id": profileId,
    },
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}

export async function GET(request: NextRequest) {
  const profileId = request.headers.get("X-Profile-Id") ?? "";

  const res = await fetch(`${FASTAPI_URL}/conversations`, {
    headers: { "X-Profile-Id": profileId },
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
