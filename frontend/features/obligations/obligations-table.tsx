import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"
import type { ObligationStatus, ProjectObligation } from "@/lib/types"

interface ObligationsTableProps {
  obligations: ProjectObligation[]
  loading: boolean
}

const HEAD_CLASS = "text-xs font-semibold uppercase tracking-wide text-slate-500"

// Format an ISO date (YYYY-MM-DD) as DD/MM/YYYY without timezone drift.
function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-")
  if (!year || !month || !day) return isoDate
  return `${day}/${month}/${year}`
}

// Status colours mirror the "Próximas obligaciones" widget in dashboard.png:
// overdue red, upcoming amber, on-track green.
const STATUS_BADGE: Record<ObligationStatus, string> = {
  Vencido: "bg-red-100 text-red-700",
  Próximo: "bg-amber-100 text-amber-700",
  "Al día": "bg-green-100 text-green-700",
}

const STATUS_DOT: Record<ObligationStatus, string> = {
  Vencido: "bg-red-500",
  Próximo: "bg-amber-500",
  "Al día": "bg-green-500",
}

export function ObligationsTable({ obligations, loading }: ObligationsTableProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Obligación</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Estado</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Vencimiento</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={3} className="px-6 py-12 text-center text-sm text-slate-500">
                Cargando obligaciones...
              </TableCell>
            </TableRow>
          ) : obligations.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={3} className="px-6 py-12 text-center text-sm text-slate-500">
                No se han encontrado obligaciones.
              </TableCell>
            </TableRow>
          ) : (
            obligations.map((obligation) => (
              <TableRow key={obligation.id} className="border-slate-100">
                <TableCell className="px-6 py-4">
                  <div className="flex items-start gap-3">
                    <span
                      className={cn(
                        "mt-1.5 size-2 shrink-0 rounded-full",
                        STATUS_DOT[obligation.status],
                      )}
                    />
                    <div className="min-w-0">
                      <p className="font-semibold text-slate-900">
                        {obligation.obligation.name}
                      </p>
                      <p className="truncate text-sm text-slate-500">
                        {obligation.project.name} · {obligation.client.name}
                      </p>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="px-6 py-4">
                  <Badge
                    variant="secondary"
                    className={cn("font-medium", STATUS_BADGE[obligation.status])}
                  >
                    {obligation.status}
                  </Badge>
                </TableCell>
                <TableCell className="px-6 py-4 text-slate-700">
                  {formatDate(obligation.dueDate)}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}
