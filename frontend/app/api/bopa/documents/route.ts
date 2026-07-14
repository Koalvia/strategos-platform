import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import type { BopaDocumentPage } from "@/features/bopa/api"

// Query params forwarded verbatim to the backend's GET /bopa/documents.
const FORWARDED_PARAMS = [
  "q",
  "organisme",
  "tema",
  "organisme_pare",
  "tema_pare",
  "year",
  "date_from",
  "date_to",
  "limit",
  "offset",
] as const

export async function GET(request: NextRequest) {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const { searchParams } = new URL(request.url)
    const query = new URLSearchParams()
    for (const key of FORWARDED_PARAMS) {
      const value = searchParams.get(key)
      if (value) query.set(key, value)
    }
    const queryString = query.toString()

    const data = await apiFetch<BopaDocumentPage>(
      `${config.api.endpoints.backend.bopa.documents}${queryString ? `?${queryString}` : ""}`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      },
    )

    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Search BOPA documents error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to fetch BOPA documents" },
      { status: 500 },
    )
  }
}
