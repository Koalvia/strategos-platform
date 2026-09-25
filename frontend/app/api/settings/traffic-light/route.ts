import { type NextRequest, NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import type { TrafficLightSettings } from "@/features/settings/api"

export async function GET() {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const data = await apiFetch<TrafficLightSettings>(
      config.api.endpoints.backend.settings.trafficLight,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      },
    )

    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Get traffic-light settings error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to fetch traffic-light settings" },
      { status: 500 },
    )
  }
}

export async function PUT(request: NextRequest) {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const body = await request.json()

    const data = await apiFetch<TrafficLightSettings>(
      config.api.endpoints.backend.settings.trafficLight,
      {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          yellow_within_days: body.yellow_within_days,
          red_within_days: body.red_within_days,
          email_on_change_enabled: body.email_on_change_enabled,
        }),
      },
    )

    return NextResponse.json({ success: true, data })
  } catch (error) {
    console.error("[Strategos] Update traffic-light settings error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json({ success: false, message: error.message }, { status: error.status })
    }

    return NextResponse.json(
      { success: false, message: "Failed to update traffic-light settings" },
      { status: 500 },
    )
  }
}
