import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import {
  type ObligationProjectOption,
  type ProjectObligationPageResponse,
  transformProjectObligationResponse,
} from "@/lib/types"

export async function GET(request: NextRequest) {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const { searchParams } = new URL(request.url)

    // The "Proyecto" filter's option list instead of a page of rows: forwards to
    // the backend's /obligations/projects.
    if (searchParams.get("options") === "projects") {
      const projects = await apiFetch<ObligationProjectOption[]>(
        config.api.endpoints.backend.obligations.projects,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      )

      return NextResponse.json({ success: true, data: projects })
    }

    const status = searchParams.get("status")
    const projectId = searchParams.get("project_id")
    const dueAfter = searchParams.get("due_after")
    const dueBefore = searchParams.get("due_before")
    const page = searchParams.get("page")
    const pageSize = searchParams.get("page_size")

    // Forward the optional filters and the page window; both filtering and paging
    // happen server-side. Absent params are not forwarded, which is what keeps the
    // complete-list callers working: no page_size in, no page_size out.
    const query = new URLSearchParams()
    if (status) query.set("status", status)
    if (projectId) query.set("project_id", projectId)
    if (dueAfter) query.set("due_after", dueAfter)
    if (dueBefore) query.set("due_before", dueBefore)
    if (page) query.set("page", page)
    if (pageSize) query.set("page_size", pageSize)
    const queryString = query.toString()

    const backendPage = await apiFetch<ProjectObligationPageResponse>(
      `${config.api.endpoints.backend.obligations.base}${queryString ? `?${queryString}` : ""}`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    )

    // Unwrapped rather than passed through, so `data` stays a plain array for the
    // screens that only want the list, with `meta` alongside for the one that pages.
    return NextResponse.json({
      success: true,
      data: backendPage.items.map(transformProjectObligationResponse),
      meta: backendPage.meta,
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
