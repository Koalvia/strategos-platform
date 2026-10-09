import { NextResponse } from "next/server"
import { apiFetch } from "@/lib/api-client"
import { config } from "@/lib/config"

// Read at request time so the flag lives in the backend, not in the frontend build.
export const dynamic = "force-dynamic"

export async function GET() {
  try {
    const data = await apiFetch<{ microsoft: boolean }>(config.api.endpoints.backend.auth.sso)
    return NextResponse.json({ microsoft: Boolean(data.microsoft) })
  } catch (error) {
    console.error("[Strategos] SSO status error:", error)
    return NextResponse.json({ microsoft: false })
  }
}
