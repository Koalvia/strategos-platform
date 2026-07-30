// Arrow icons for the Anterior / Siguiente buttons, the same two the dashboard's
// "Facturación" footer uses.
import { ChevronLeft, ChevronRight } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"
import type { ObligationStatus, PageMeta, ProjectObligation } from "@/lib/types"

interface ObligationsTableProps {
  obligations: ProjectObligation[]
  loading: boolean
  // Pagination is opt-in: pass both to get the page footer. Callers that render
  // every obligation of a single project (the project detail screen) omit them and
  // need no other change. Keeping these optional is why that screen compiles
  // untouched — and the signature has to be right by design, because
  // next.config.mjs sets typescript.ignoreBuildErrors, so `pnpm build` would not
  // have flagged a mismatch.
  meta?: PageMeta | null
  onPageChange?: (page: number) => void
}

const HEAD_CLASS = "text-xs font-semibold uppercase tracking-wide text-slate-500"

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

export function ObligationsTable({
  obligations,
  loading,
  meta,
  onPageChange,
}: ObligationsTableProps) {
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

      {/* Hidden when everything fits on one page, and when the caller opted out. */}
      {onPageChange && meta && meta.total_pages > 1 && (
        <div className="flex items-center justify-between border-t border-slate-100 px-6 py-4">
          <p className="text-sm text-slate-500">
            Página {meta.page} de {meta.total_pages} · {meta.total_count} obligaciones
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={loading || !meta.has_prev}
              onClick={() => onPageChange(meta.page - 1)}
            >
              <ChevronLeft />
              Anterior
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={loading || !meta.has_next}
              onClick={() => onPageChange(meta.page + 1)}
            >
              Siguiente
              <ChevronRight />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
