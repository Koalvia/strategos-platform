import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { getAuthToken } from "@/lib/auth"
import type { Customer } from "@/lib/types"

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

    const data = await apiFetch<Customer>(
      `/api/v1/customers/${encodeURIComponent(customer_id)}`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      },
    )

    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Get customer error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to fetch customer" },
      { status: 500 },
    )
  }
}
