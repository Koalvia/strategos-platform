import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { getInitials } from "@/lib/navigation"
import { cn } from "@/lib/utils"
import type { UserDirectoryEntry } from "@/lib/types"

interface UsersTableProps {
  users: UserDirectoryEntry[]
  loading: boolean
}

const HEAD_CLASS = "text-xs font-semibold uppercase tracking-wide text-slate-500"

export function UsersTable({ users, loading }: UsersTableProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Nombre</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Rol</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Email</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Tareas activas</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={4} className="px-6 py-12 text-center text-sm text-slate-500">
                Cargando usuarios...
              </TableCell>
            </TableRow>
          ) : users.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={4} className="px-6 py-12 text-center text-sm text-slate-500">
                No se han encontrado usuarios.
              </TableCell>
            </TableRow>
          ) : (
            users.map((user) => (
              <TableRow key={user.email} className="border-slate-100">
                <TableCell className="px-6 py-4">
                  <div className="flex items-center gap-3">
                    <Avatar className="size-9">
                      <AvatarFallback className="bg-[#0e1729] text-xs font-semibold text-white">
                        {getInitials(user.name)}
                      </AvatarFallback>
                    </Avatar>
                    <span className="font-semibold text-slate-900">{user.name}</span>
                  </div>
                </TableCell>
                <TableCell className="px-6 py-4 text-slate-700">{user.role ?? "—"}</TableCell>
                <TableCell className="px-6 py-4 text-slate-500">{user.email}</TableCell>
                <TableCell className="px-6 py-4 text-slate-700">{user.activeTasks}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}
