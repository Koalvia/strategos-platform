import { type NextRequest, NextResponse } from "next/server"
import { cookies } from "next/headers"
import { apiFetch } from "@/lib/api-client"
import { config } from "@/lib/config"
import { publicUrl } from "@/lib/public-url"

export async function GET(request: NextRequest) {
  try {
    const data = await apiFetch<{ authorization_url: string; flow: object }>(
      config.api.endpoints.backend.auth.microsoftLogin,
    )
    const cookieStore = await cookies()
    cookieStore.set("ms-sso-flow", JSON.stringify(data.flow), {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      maxAge: 600,
    })
    return NextResponse.redirect(data.authorization_url)
  } catch (error) {
    console.error("[Strategos] Microsoft SSO start error:", error)
    return NextResponse.redirect(publicUrl(request, "/login?error=sso_failed"))
  }
}
