import { NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import type { BopaFilterOptions } from "@/features/bopa/api"

export async function GET() {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const data = await apiFetch<BopaFilterOptions>(
      config.api.endpoints.backend.bopa.documentFilters,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      },
    )

    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Get BOPA document filters error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to fetch BOPA filters" },
      { status: 500 },
    )
  }
}
