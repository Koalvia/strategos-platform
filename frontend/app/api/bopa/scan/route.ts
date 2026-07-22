import { NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { getAuthToken } from "@/lib/auth"
import type { BopaScanResult } from "@/features/bopa/api"

// Triggers a BOPA scan on the backend (sync -> analyze) and returns its outcome.
// Runs synchronously on the backend, so the response arrives once the scan has
// persisted its results. An optional `customer_id` query param is forwarded
// verbatim to scope the scan to a single customer.
export async function POST(request: Request) {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const customerId = new URL(request.url).searchParams.get("customer_id")
    const query = customerId ? `?customer_id=${encodeURIComponent(customerId)}` : ""

    const data = await apiFetch<BopaScanResult>(`/api/v1/bopa/scan${query}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    })

    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] BOPA scan error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to run BOPA scan" },
      { status: 500 },
    )
  }
}
