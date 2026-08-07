import { NextRequest, NextResponse } from "next/server";

const FASTAPI_URL = process.env.FASTAPI_URL;

export async function POST(request: NextRequest) {
    const body = await request.text(); // form-encoded body, pass through raw
    const res = await fetch(`${FASTAPI_URL}/profiles/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
    });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
}