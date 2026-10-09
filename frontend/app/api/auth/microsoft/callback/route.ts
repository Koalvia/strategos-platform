import { type NextRequest, NextResponse } from "next/server"
import { cookies } from "next/headers"
import { apiFetch, ApiError } from "@/lib/api-client"
import { config } from "@/lib/config"

// Behind a reverse proxy request.url carries the internal host, so prefer the
// forwarded public host when the proxy sets it.
function publicUrl(request: NextRequest, path: string) {
    const host = request.headers.get("x-forwarded-host")
    const proto = request.headers.get("x-forwarded-proto") ?? "https"
    return host ? new URL(path, `${proto}://${host}`) : new URL(path, request.url)
}

export async function GET(request: NextRequest) {
    const cookieStore = await cookies()
    const flow = cookieStore.get("ms-sso-flow")?.value
    cookieStore.delete("ms-sso-flow")
    const fail = (code: string) => NextResponse.redirect(publicUrl(request, `/login?error=${code}`))
    if (!flow) return fail("sso_expired")
    try {
        const data = await apiFetch<{ access_token: string }>(
            config.api.endpoints.backend.auth.microsoftCallback,
            {
                method: "POST",
                body: JSON.stringify({
                    flow: JSON.parse(flow),
                    auth_response: Object.fromEntries(request.nextUrl.searchParams),
                }),
            },
        )
        cookieStore.set("auth-token", data.access_token, {
            httpOnly: true,
            secure: process.env.NODE_ENV === "production",
            sameSite: "lax",
            maxAge: 60 * 60 * 24 * 7,
        })
        return NextResponse.redirect(publicUrl(request, "/dashboard"))
    } catch (error) {
        return fail(error instanceof ApiError && error.status === 403 ? "sso_no_account" : "sso_failed")
    }
}
