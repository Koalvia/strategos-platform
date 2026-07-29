import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import type { CustomerBillingPage } from "@/lib/types"

export async function GET(request: NextRequest) {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const { searchParams } = new URL(request.url)
    const page = searchParams.get("page")
    const pageSize = searchParams.get("page_size")

    // Forward the pagination window to the backend, which fetches exactly this
    // page's customers from Business Central and reports the real total in
    // `meta`.
    const query = new URLSearchParams()
    if (page) query.set("page", page)
    if (pageSize) query.set("page_size", pageSize)
    const queryString = query.toString()

    const data = await apiFetch<CustomerBillingPage | null>(
      `${config.api.endpoints.backend.dashboard.billing}${queryString ? `?${queryString}` : ""}`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      },
    )

    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Get dashboard billing error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to fetch billing summary" },
      { status: 500 },
    )
  }
}

