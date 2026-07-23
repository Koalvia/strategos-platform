import { NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { getAuthToken } from "@/lib/auth"
import type { BopaScanResult } from "@/features/bopa/api"

// Triggers a full BOPA scan on the backend (sync -> analyze -> alerts) and
// returns its outcome. Runs synchronously on the backend, so the response
// arrives once the scan has persisted its results.
export async function POST() {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const data = await apiFetch<BopaScanResult>("/api/v1/bopa/scan", {
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
