import { NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import {
  type ProjectObligationResponse,
  transformProjectObligationResponse,
} from "@/lib/types"

export async function GET() {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const backendObligations = await apiFetch<ProjectObligationResponse[] | null>(
      config.api.endpoints.backend.dashboard.obligations,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      },
    )

    // null means Business Central could not serve the widget — kept distinct
    // from an empty list, which legitimately means "nothing due".
    const data = backendObligations
      ? backendObligations.map(transformProjectObligationResponse)
      : null

    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Get dashboard obligations error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to fetch upcoming obligations" },
      { status: 500 },
    )
  }
}
