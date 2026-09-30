import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"

// Persist the shared vertical order of a board column. Proxies to the backend
// (which enforces the union move rule) and passes its 403/404 through.
export async function PUT(request: NextRequest) {
  try {
    const token = await getAuthToken()
    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const body = await request.json()

    await apiFetch(config.api.endpoints.backend.tasks.boardOrder, {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ ordered: body.ordered }),
    })

    return NextResponse.json({ success: true })
  } catch (error) {
    console.error("[Strategos] Reorder board error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to reorder board" },
      { status: 500 },
    )
  }
}
