import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = process.env.FASTAPI_URL;

// GET /api/conversations/{id}/dataframes -> dataframes available for
// "Make your own graph" (columns + a small preview), scoped to the
// authenticated profile's own conversation/portfolio.
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const profileId = request.headers.get("X-Profile-Id") ?? "";
  const res = await fetch(`${FASTAPI_URL}/conversations/${id}/dataframes`, {
    headers: { "X-Profile-Id": profileId },
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
