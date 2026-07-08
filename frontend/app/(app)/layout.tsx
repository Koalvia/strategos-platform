"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import { Loader2 } from "lucide-react"

import { authApi } from "@/features/auth/api"
import { AppSidebar } from "@/components/app-sidebar"

interface ShellUser {
  name?: string | null
  email?: string | null
  role?: string | null
}

export default function AppLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const [user, setUser] = useState<ShellUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true

    const loadUser = async () => {
      try {
        const result = await authApi.getCurrentUser()
        if (!active) return
        if (!result.success) {
          router.push("/login")
          return
        }
        setUser(result.user)
      } catch (error) {
        console.error("[Strategos] App shell auth error:", error)
        if (active) router.push("/login")
      } finally {
        if (active) setLoading(false)
      }
    }

    loadUser()
    return () => {
      active = false
    }
  }, [router])

  const handleLogout = async () => {
    await authApi.logout()
    router.push("/login")
  }

  if (loading || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader2 className="size-8 animate-spin text-[#caa53d]" />
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-slate-50 text-slate-900">
      <AppSidebar user={user} onLogout={handleLogout} />
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  )
}
