import {
  LayoutDashboard,
  Users,
  FolderKanban,
  ListTodo,
  Clock,
  Newspaper,
  Settings,
  Bell,
  type LucideIcon,
} from "lucide-react"

export interface NavItem {
  label: string
  href: string
  icon: LucideIcon
}

export interface NavGroup {
  label: string
  items: NavItem[]
}

// Shared navigation config for the authenticated app shell.
// Consumed by the sidebar in `app/(app)/layout.tsx`.
export const navGroups: NavGroup[] = [
  {
    label: "OPERATIVA",
    items: [
      { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
      { label: "Clientes", href: "/clientes", icon: Users },
      { label: "Proyectos", href: "/proyectos", icon: FolderKanban },
      { label: "Tareas", href: "/tareas", icon: ListTodo },
    ],
  },
  {
    label: "GESTIÓN",
    items: [
      { label: "Obligaciones", href: "/obligaciones", icon: Clock },
      { label: "BOPA", href: "/bopa", icon: Newspaper },
      { label: "Usuarios", href: "/usuarios", icon: Settings },
      { label: "Alertas", href: "/alerts", icon: Bell },
    ],
  },
]

/** Build up-to-two-letter initials from a display name (e.g. "Marc Solé" -> "MS"). */
export function getInitials(name?: string | null): string {
  if (!name) return "?"
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "?"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}
