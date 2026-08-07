import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = process.env.FASTAPI_URL;

export async function POST(request: NextRequest) {
    const { search } = new URL(request.url);
    const res = await fetch(`${FASTAPI_URL}/profiles/signup${search}`, {
        method: "POST",
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
}