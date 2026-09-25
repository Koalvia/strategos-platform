import { NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"

interface AlertPreference {
  category: string
  email_enabled: boolean
}
interface AlertPreferencesResponse {
  items: AlertPreference[]
}

export async function GET() {
  try {
    const token = await getAuthToken()
    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }
    const data = await apiFetch<AlertPreferencesResponse>(
      config.api.endpoints.backend.alerts.preferences,
      { method: "GET", headers: { Authorization: `Bearer ${token}` } },
    )
    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Alert preferences GET error:", error)
    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }
    return NextResponse.json(
      { success: false, message: "Failed to load alert preferences" },
      { status: 500 },
    )
  }
}

export async function PUT(request: Request) {
  try {
    const token = await getAuthToken()
    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }
    const body = await request.json()
    const data = await apiFetch<AlertPreferencesResponse>(
      config.api.endpoints.backend.alerts.preferences,
      {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      },
    )
    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Alert preferences PUT error:", error)
    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }
    return NextResponse.json(
      { success: false, message: "Failed to update alert preferences" },
      { status: 500 },
    )
  }
}
