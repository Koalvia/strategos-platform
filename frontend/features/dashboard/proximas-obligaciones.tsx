import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import type { ObligationStatus, ProjectObligation } from "@/lib/types"

interface ProximasObligacionesProps {
  // null when Business Central could not serve this section — rendered as an
  // explicit "unavailable" notice rather than as "no hay obligaciones", which
  // would wrongly suggest there is nothing due.
  obligations: ProjectObligation[] | null
  // True while this section's own request is in flight. Checked before the
  // `null` branch: `obligations` starts null, and a pending load must not be
  // reported as a Business Central failure.
  isLoading?: boolean
}

// Placeholder rows shown while the list loads. The real length is unknown until
// it arrives, so this is a plausible height rather than an exact match.
const SKELETON_ROWS = 4

// Format an ISO date (YYYY-MM-DD) as DD/MM/YYYY without timezone drift.
// Undated obligations (status "Sin fecha") carry a null due date.
function formatDate(isoDate: string | null): string {
  if (!isoDate) return "Sin fecha"
  const [year, month, day] = isoDate.split("-")
  if (!year || !month || !day) return isoDate
  return `${day}/${month}/${year}`
}

// Status colours mirror the "Próximas obligaciones" widget in dashboard.png:
// overdue red, upcoming amber, on-track green, undated neutral.
const STATUS_BADGE: Record<ObligationStatus, string> = {
  Vencido: "bg-red-100 text-red-700",
  Próximo: "bg-amber-100 text-amber-700",
  "Al día": "bg-green-100 text-green-700",
  "Sin fecha": "bg-slate-100 text-slate-500",
}

const STATUS_DOT: Record<ObligationStatus, string> = {
  Vencido: "bg-red-500",
  Próximo: "bg-amber-500",
  "Al día": "bg-green-500",
  "Sin fecha": "bg-slate-400",
}

export function ProximasObligaciones({
  obligations,
  isLoading = false,
}: ProximasObligacionesProps) {
  return (
    <Card className="gap-0 border-slate-200 py-0">
      <h2 className="border-b border-slate-100 px-6 py-5 text-lg font-bold text-slate-900">
        Próximas obligaciones
      </h2>
      {isLoading ? (
        <ul className="divide-y divide-slate-100">
          {Array.from({ length: SKELETON_ROWS }, (_, index) => (
            <li key={index} className="flex items-center gap-4 px-6 py-4">
              <Skeleton className="size-2 shrink-0 rounded-full" />
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-56" />
              </div>
              <Skeleton className="h-6 w-20 shrink-0" />
              <Skeleton className="h-4 w-20 shrink-0" />
            </li>
          ))}
        </ul>
      ) : obligations === null ? (
        <p className="px-6 py-12 text-center text-sm text-slate-500">
          No se han podido cargar las obligaciones desde Business Central.
        </p>
      ) : obligations.length === 0 ? (
        <p className="px-6 py-12 text-center text-sm text-slate-500">
          No hay obligaciones próximas.
        </p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {obligations.map((obligation) => (
            <li
              key={obligation.id}
              className="flex items-center gap-4 px-6 py-4"
            >
              <span
                className={cn(
                  "size-2 shrink-0 rounded-full",
                  STATUS_DOT[obligation.status],
                )}
              />
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-slate-900">
                  {obligation.obligation.name}
                </p>
                <p className="truncate text-sm text-slate-500">
                  {obligation.project.name} · {obligation.client.name}
                </p>
              </div>
              <Badge
                variant="secondary"
                className={cn("font-medium", STATUS_BADGE[obligation.status])}
              >
                {obligation.status}
              </Badge>
              <span className="shrink-0 text-sm text-slate-700">
                {formatDate(obligation.dueDate)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
