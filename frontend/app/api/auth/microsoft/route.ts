import { NextResponse } from "next/server"
import { cookies } from "next/headers"
import { apiFetch } from "@/lib/api-client"
import { config } from "@/lib/config"

export async function GET() {
    const data = await apiFetch<{ authorization_url: string, flow: object }>(
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
}
