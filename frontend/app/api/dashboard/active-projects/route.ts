import { NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import type { ActiveTotalKpi } from "@/lib/types"

export async function GET() {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    // null when Business Central could not serve this widget; forwarded as-is so
    // the tile can show "No disponible" instead of a misleading figure.
    const data = await apiFetch<ActiveTotalKpi | null>(
      config.api.endpoints.backend.dashboard.activeProjects,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      },
    )

    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Get dashboard active projects error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to fetch active projects" },
      { status: 500 },
    )
  }
}
