import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { getAuthToken } from "@/lib/auth"
import type { BopaDocumentPage } from "@/features/bopa/api"

// Query params forwarded verbatim to the backend's GET /customers/{id}/bopa-matches.
const FORWARDED_PARAMS = ["limit", "offset"] as const

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ customer_id: string }> },
) {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const { customer_id } = await params

    const { searchParams } = new URL(request.url)
    const query = new URLSearchParams()
    for (const key of FORWARDED_PARAMS) {
      const value = searchParams.get(key)
      if (value) query.set(key, value)
    }
    const queryString = query.toString()

    const data = await apiFetch<BopaDocumentPage>(
      `/api/v1/customers/${encodeURIComponent(customer_id)}/bopa-matches${
        queryString ? `?${queryString}` : ""
      }`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      },
    )

    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Search customer BOPA matches error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to fetch customer BOPA matches" },
      { status: 500 },
    )
  }
}
