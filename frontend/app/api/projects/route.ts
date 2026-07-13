import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import { type ProjectPageResponse, transformProjectPageResponse } from "@/lib/types"

export async function GET(request: NextRequest) {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const { searchParams } = new URL(request.url)
    const search = searchParams.get("search")
    const projectType = searchParams.get("project_type")
    const entityType = searchParams.get("entity_type")
    const status = searchParams.get("status")
    const cursor = searchParams.get("cursor")

    // Forward the optional filters/cursor to the backend (server-side
    // filtering and pagination).
    const query = new URLSearchParams()
    if (search) query.set("search", search)
    if (projectType) query.set("project_type", projectType)
    if (entityType) query.set("entity_type", entityType)
    if (status) query.set("status", status)
    if (cursor) query.set("cursor", cursor)
    const queryString = query.toString()

    const backendPage = await apiFetch<ProjectPageResponse>(
      `${config.api.endpoints.backend.projects.base}${queryString ? `?${queryString}` : ""}`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    )

    return NextResponse.json({
      success: true,
      data: transformProjectPageResponse(backendPage),
    })
  } catch (error) {
    console.error("[Strategos] Get projects error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json(
        { success: false, message: error.message },
        { status: error.status },
      )
    }

    return NextResponse.json({ success: false, message: "Failed to fetch projects" }, { status: 500 })
  }
}
