import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import type { Project, ProjectObligation } from "@/lib/types"

interface ProjectCardProps {
  project: Project
  nextObligation?: ProjectObligation
}

// Format an ISO date (YYYY-MM-DD) as DD/MM/YYYY without timezone drift.
function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-")
  if (!year || !month || !day) return isoDate
  return `${day}/${month}/${year}`
}

// Colour the next-obligation line by its derived due state: red when overdue,
// amber when upcoming, neutral otherwise.
const OBLIGATION_COLOR: Record<ProjectObligation["status"], string> = {
  Vencido: "text-red-600",
  Próximo: "text-amber-600",
  "Al día": "text-slate-500",
}

export function ProjectCard({ project, nextObligation }: ProjectCardProps) {
  return (
    <Card className="gap-4 border-slate-200 px-5 py-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="truncate text-base font-bold text-slate-900">{project.name}</h2>
          <p className="truncate text-sm text-slate-500">{project.customer.name}</p>
        </div>
        <Badge
          variant="secondary"
          className={cn(
            "shrink-0 font-medium",
            project.status === "Activo"
              ? "bg-green-100 text-green-700"
              : "bg-slate-100 text-slate-500",
          )}
        >
          {project.status}
        </Badge>
      </div>

      <div className="flex flex-wrap gap-2">
        <Badge variant="secondary" className="bg-slate-100 font-medium text-slate-600">
          {project.projectType}
        </Badge>
        <Badge variant="secondary" className="bg-slate-100 font-medium text-slate-600">
          {project.entityType}
        </Badge>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-4">
        <p className="text-sm text-slate-500">
          Resp. {project.responsible} · Tèc. {project.technician}
        </p>
        {nextObligation ? (
          <p
            className={cn(
              "text-sm font-semibold",
              OBLIGATION_COLOR[nextObligation.status],
            )}
          >
            Próx: {nextObligation.obligation.name} · {formatDate(nextObligation.dueDate)}
          </p>
        ) : null}
      </div>
    </Card>
  )
}
