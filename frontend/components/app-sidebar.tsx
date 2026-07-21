"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { LogOut } from "lucide-react"

import { cn } from "@/lib/utils"
import { navGroups, getInitials } from "@/lib/navigation"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { alertsApi } from "@/features/alerts/api"

interface AppSidebarUser {
  name?: string | null
  email?: string | null
  role?: string | null
}

interface AppSidebarProps {
  user: AppSidebarUser | null
  onLogout: () => void
}

// How often the unread-alert badge refreshes so it updates without a reload.
const UNREAD_POLL_MS = 30_000

export function AppSidebar({ user, onLogout }: AppSidebarProps) {
  const pathname = usePathname()
  const [unreadCount, setUnreadCount] = useState(0)

  // Poll the unread-alert count so the "Alertas" badge stays live. Also refetch
  // on navigation (the Alertas page mutates statuses), so acting on an alert
  // updates the badge without waiting for the next poll.
  useEffect(() => {
    let active = true

    const loadCount = async () => {
      try {
        const result = await alertsApi.getUnreadCount()
        if (active && result.success && result.data) {
          setUnreadCount(result.data.count)
        }
      } catch (error) {
        console.error("[Strategos] Load unread alert count error:", error)
      }
    }

    loadCount()
    const interval = setInterval(loadCount, UNREAD_POLL_MS)
    // The Alertas page dispatches this after mutating a status, so the badge
    // updates immediately rather than waiting for the next poll.
    window.addEventListener("alerts:changed", loadCount)
    return () => {
      active = false
      clearInterval(interval)
      window.removeEventListener("alerts:changed", loadCount)
    }
  }, [pathname])

  return (
    <aside className="flex h-screen w-[260px] shrink-0 flex-col bg-[#0e1729] text-slate-200">
      {/* Brand header */}
      <div className="flex items-center gap-3 border-b border-white/10 px-5 py-5">
        <div className="flex size-10 items-center justify-center rounded-lg bg-[#caa53d] text-lg font-bold text-[#0e1729]">
          E
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold tracking-wide text-white">
            ESTRATEGOS
          </p>
          <p className="text-xs text-slate-400">Plataforma interna</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-5">
        {navGroups.map((group) => (
          <div key={group.label} className="mb-6">
            <p className="px-3 pb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
              {group.label}
            </p>
            <ul className="space-y-1">
              {group.items.map((item) => {
                const isActive =
                  pathname === item.href ||
                  pathname.startsWith(`${item.href}/`)
                const Icon = item.icon
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={isActive ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-3 rounded-md border-l-2 border-transparent px-3 py-2 text-sm font-medium transition-colors",
                        isActive
                          ? "border-[#caa53d] bg-[#1a2540] text-white"
                          : "text-slate-300 hover:bg-white/5 hover:text-white",
                      )}
                    >
                      <Icon
                        className={cn(
                          "size-4 shrink-0",
                          isActive ? "text-[#caa53d]" : "text-slate-400",
                        )}
                      />
                      <span className="flex-1">{item.label}</span>
                      {item.href === "/alerts" && unreadCount > 0 && (
                        <span
                          className="ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1.5 text-xs font-semibold text-white"
                          aria-label={`${unreadCount} alertas sin leer`}
                        >
                          {unreadCount > 99 ? "99+" : unreadCount}
                        </span>
                      )}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* User footer */}
      <div className="flex items-center gap-3 border-t border-white/10 px-4 py-4">
        <Avatar className="size-9 bg-[#1a2540] text-slate-200">
          <AvatarFallback className="bg-[#1a2540] text-xs font-semibold text-slate-200">
            {getInitials(user?.name)}
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1 leading-tight">
          <p className="truncate text-sm font-semibold text-white">
            {user?.name ?? "—"}
          </p>
          <p className="truncate text-xs text-slate-400">
            {user?.role ?? "Usuario"}
          </p>
        </div>
        <button
          type="button"
          onClick={onLogout}
          aria-label="Cerrar sesión"
          className="rounded-md p-2 text-slate-400 transition-colors hover:bg-white/5 hover:text-white"
        >
          <LogOut className="size-4" />
        </button>
      </div>
    </aside>
  )
}
