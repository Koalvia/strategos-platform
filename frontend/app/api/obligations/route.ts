import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import {
  type ProjectObligationResponse,
  transformProjectObligationResponse,
} from "@/lib/types"

export async function GET(request: NextRequest) {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const { searchParams } = new URL(request.url)
    const status = searchParams.get("status")
    const projectId = searchParams.get("project_id")
    const dueAfter = searchParams.get("due_after")
    const dueBefore = searchParams.get("due_before")

    // Forward the optional filters to the backend (server-side filtering).
    const query = new URLSearchParams()
    if (status) query.set("status", status)
    if (projectId) query.set("project_id", projectId)
    if (dueAfter) query.set("due_after", dueAfter)
    if (dueBefore) query.set("due_before", dueBefore)
    const queryString = query.toString()

    const backendObligations = await apiFetch<ProjectObligationResponse[]>(
      `${config.api.endpoints.backend.obligations.base}${queryString ? `?${queryString}` : ""}`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    )

    const obligations = backendObligations.map(transformProjectObligationResponse)

    return NextResponse.json({
      success: true,
      data: obligations,
    })
  } catch (error) {
    console.error("[Strategos] Get obligations error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json(
        { success: false, message: error.message },
        { status: error.status },
      )
    }

    return NextResponse.json({ success: false, message: "Failed to fetch obligations" }, { status: 500 })
  }
}
