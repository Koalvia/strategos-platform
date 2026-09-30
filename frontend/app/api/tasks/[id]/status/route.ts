import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import { transformTaskResponse, type TaskResponse } from "@/lib/types"

// Move a task to a new workflow state. Proxies to the backend (which enforces the
// assignee-or-manager rule) and passes its 403/404 through so the client can react.
export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const { id } = await params
    const body = await request.json()

    const data = await apiFetch<TaskResponse>(
      config.api.endpoints.backend.tasks.status(id),
      {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ status: body.status, source: body.source }),
      },
    )

    return NextResponse.json({ success: true, data: transformTaskResponse(data) })
  } catch (error) {
    console.error("[Strategos] Update task status error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to update task status" },
      { status: 500 },
    )
  }
}
