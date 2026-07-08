import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import { type CustomerResponse, transformCustomerResponse } from "@/lib/types"

export async function GET(request: NextRequest) {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const { searchParams } = new URL(request.url)
    const search = searchParams.get("search")
    const status = searchParams.get("status")

    // Forward the optional search/status filters to the backend (server-side filtering).
    const query = new URLSearchParams()
    if (search) query.set("search", search)
    if (status) query.set("status", status)
    const queryString = query.toString()

    const backendCustomers = await apiFetch<CustomerResponse[]>(
      `${config.api.endpoints.backend.customers.base}${queryString ? `?${queryString}` : ""}`,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    )

    const customers = backendCustomers.map(transformCustomerResponse)

    return NextResponse.json({
      success: true,
      data: customers,
    })
  } catch (error) {
    console.error("[Strategos] Get customers error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json(
        { success: false, message: error.message },
        { status: error.status },
      )
    }

    return NextResponse.json({ success: false, message: "Failed to fetch customers" }, { status: 500 })
  }
}
