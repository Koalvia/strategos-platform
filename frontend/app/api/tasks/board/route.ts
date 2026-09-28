import { NextRequest, NextResponse } from "next/server"
import { apiFetch } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import { transformTaskResponse, type TaskResponse } from "@/lib/types"

// The Tareas board: BC tasks + obligations shown as tasks, scoped by the backend.
export async function GET(request: NextRequest) {
  const token = await getAuthToken()
  if (!token) {
    return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
  }

  const status = request.nextUrl.searchParams.get("status")
  const query = status ? `?status=${encodeURIComponent(status)}` : ""

  try {
    const cards = await apiFetch<TaskResponse[]>(
      config.api.endpoints.backend.tasks.board + query,
      { method: "GET", headers: { Authorization: `Bearer ${token}` } },
    )
    return NextResponse.json({ success: true, data: cards.map(transformTaskResponse) })
  } catch (error) {
    console.error("[Strategos] Load board error:", error)
    return NextResponse.json(
      { success: false, message: "Failed to load board" },
      { status: 500 },
    )
  }
}
