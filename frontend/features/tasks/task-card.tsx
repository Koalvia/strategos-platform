import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import {
  STATUS_BADGE,
  STATUS_DOT,
  TRAFFIC_LIGHT_LABEL,
} from "@/features/obligations/status-style"
import type { ReactNode } from "react"

import { getInitials } from "@/lib/navigation"
import { cn } from "@/lib/utils"
import type { Task, TaskPriority } from "@/lib/types"

interface TaskCardProps {
  task: Task
  action?: ReactNode
}

// Format an ISO date (YYYY-MM-DD) as DD/MM/YYYY without timezone drift.
function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-")
  if (!year || !month || !day) return isoDate
  return `${day}/${month}/${year}`
}

// Priority badge colours mirror the task cards in tareas.png: Alta red,
// Media amber, Baja grey.
const PRIORITY_BADGE: Record<TaskPriority, string> = {
  Alta: "bg-red-100 text-red-700",
  Media: "bg-amber-100 text-amber-700",
  Baja: "bg-slate-100 text-slate-600",
}

export function TaskCard({ task, action }: TaskCardProps) {
  const traffic = task.trafficLight
  return (
    <Card className="gap-4 border-slate-200 px-5 py-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          {traffic && (
            <span
              className={cn(
                "mt-1.5 size-2 shrink-0 rounded-full",
                STATUS_DOT[traffic],
              )}
            />
          )}
          <div className="min-w-0">
            <h3 className="text-base font-bold text-slate-900">{task.title}</h3>
            <p className="truncate text-sm text-slate-500">
              {task.project.name}
              {task.client ? ` · ${task.client.name}` : ""}
            </p>
          </div>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {traffic && (
            <Badge
              variant="secondary"
              className={cn("font-medium", STATUS_BADGE[traffic])}
            >
              {TRAFFIC_LIGHT_LABEL[traffic]}
            </Badge>
          )}
          {task.priority && (
            <Badge
              variant="secondary"
              className={cn("font-medium", PRIORITY_BADGE[task.priority])}
            >
              {task.priority}
            </Badge>
          )}
        </div>
        {task.dueDate ? (
          <span className="text-sm text-slate-500">{formatDate(task.dueDate)}</span>
        ) : (
          <span className="text-xs text-slate-400">
            (no se ha especificado fecha de vencimiento)
          </span>
        )}
      </div>

      {task.assignee && (
        <div className="flex items-center gap-2 border-t border-slate-100 pt-4">
          <Avatar className="size-7">
            <AvatarFallback className="bg-[#0e1729] text-xs font-semibold text-white">
              {getInitials(task.assignee.name)}
            </AvatarFallback>
          </Avatar>
          <span className="truncate text-sm text-slate-700">
            {task.assignee.name}
          </span>
        </div>
      )}
    </Card>
  )
}
