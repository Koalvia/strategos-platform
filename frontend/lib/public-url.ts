import type { NextRequest } from "next/server"

// Behind a reverse proxy request.url carries the internal host, so prefer the
// forwarded public host when the proxy sets it.
export function publicUrl(request: NextRequest, path: string) {
  const host = request.headers.get("x-forwarded-host")
  const proto = request.headers.get("x-forwarded-proto") ?? "https"
  return host ? new URL(path, `${proto}://${host}`) : new URL(path, request.url)
}
