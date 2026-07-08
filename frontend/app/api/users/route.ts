import { NextResponse } from "next/server"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"
import { getAuthToken } from "@/lib/auth"
import { type UserDirectoryResponse, transformUserDirectoryResponse } from "@/lib/types"

export async function GET() {
  try {
    const token = await getAuthToken()

    if (!token) {
      return NextResponse.json({ success: false, message: "Unauthorized" }, { status: 401 })
    }

    const backendUsers = await apiFetch<UserDirectoryResponse[]>(
      config.api.endpoints.backend.users.base,
      {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      }
    )

    const users = backendUsers.map(transformUserDirectoryResponse)

    return NextResponse.json({
      success: true,
      data: users,
    })
  } catch (error) {
    console.error("[Strategos] Get users error:", error)

    if (error instanceof ApiError) {
      return NextResponse.json(
        { success: false, message: error.message },
        { status: error.status },
      )
    }

    return NextResponse.json({ success: false, message: "Failed to fetch users" }, { status: 500 })
  }
}
