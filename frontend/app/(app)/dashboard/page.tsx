"use client"

import { useEffect, useRef, useState } from "react"
import { Loader2, TriangleAlert } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { authApi } from "@/features/auth/api"
import { dashboardApi } from "@/features/dashboard/api"
import { FacturacionResumen } from "@/features/dashboard/facturacion-resumen"
import { UNAVAILABLE } from "@/features/dashboard/format"
import { KpiTile } from "@/features/dashboard/kpi-tile"
import { ProximasObligaciones } from "@/features/dashboard/proximas-obligaciones"
import type {
  ActiveTotalKpi,
  ApiResponse,
  CountKpi,
  CustomerBillingPage,
  PendingTotalKpi,
  ProjectObligation,
} from "@/lib/types"

// Spanish labels for the backend's section keys (which are English, per the
// repo's code-language policy). Anything unmapped falls back to the raw key so a
// newly added section still names itself rather than disappearing.
const SECTION_LABELS: Record<string, string> = {
  customers: "Clientes",
  projects: "Proyectos",
  tasks: "Tareas",
  obligations: "Obligaciones",
  billing: "Facturación",
}

function sectionLabel(key: string): string {
  return SECTION_LABELS[key] ?? key
}

// Sublabel for a KPI tile whose figure could not be loaded.
const KPI_UNAVAILABLE = "No disponible"

// Customer groups per page in the "Facturación" table.
const BILLING_PAGE_SIZE = 10

// Time-of-day greeting, matching the "Buenos días" copy in dashboard.png.
function getGreeting(hour: number): string {
  if (hour < 12) return "Buenos días"
  if (hour < 20) return "Buenas tardes"
  return "Buenas noches"
}

// "domingo, 5 de julio" — the subline date, formatted in Spanish.
function formatToday(date: Date): string {
  return date.toLocaleDateString("es-ES", {
    weekday: "long",
    day: "numeric",
    month: "long",
  })
}

// One widget per endpoint, so a Business Central outage behind one of them
// degrades only its own figure.
interface DashboardSections {
  proyectosActivos: ActiveTotalKpi | null
  obligacionesProximas: CountKpi | null
  tareasPendientes: PendingTotalKpi | null
  clientesActivos: ActiveTotalKpi | null
  proximasObligaciones: ProjectObligation[] | null
  facturacion: CustomerBillingPage | null
}

// Resolve one widget to its payload, or to null when it could not be loaded.
// A failed request and an unavailable Business Central source are the same thing
// to the reader — both mean "this figure is unknown" — so both collapse to null
// and get named in the notice above the panel. Never rejects, so one broken
// widget cannot take the other five down with it.
async function loadSection<T>(
  load: () => Promise<ApiResponse<T | null>>,
): Promise<T | null> {
  try {
    const result = await load()
    return result.success ? (result.data ?? null) : null
  } catch (error) {
    console.error("[Strategos] Load dashboard section error:", error)
    return null
  }
}

// Rebuild the list of unavailable sources the monolithic endpoint used to
// report. Now that each widget has its own endpoint, a null payload *is* that
// signal, so the notice is reconstructed here instead of being served.
function unavailableSections(sections: DashboardSections): string[] {
  const missing: string[] = []
  if (sections.clientesActivos === null) missing.push("customers")
  if (sections.proyectosActivos === null) missing.push("projects")
  if (sections.tareasPendientes === null) missing.push("tasks")
  // Both obligation widgets read the same source, so they name it once.
  if (
    sections.obligacionesProximas === null ||
    sections.proximasObligaciones === null
  ) {
    missing.push("obligations")
  }
  if (sections.facturacion === null) missing.push("billing")
  return missing
}

export default function DashboardPage() {
  const [name, setName] = useState<string | null>(null)
  const [sections, setSections] = useState<DashboardSections | null>(null)
  // Why the panel is missing, when it is. Kept separate from `sections` so a
  // failed load is distinguishable from a panel that legitimately has no data.
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [billingPage, setBillingPage] = useState(1)
  // Paging billing hits Business Central for that page's customers, so the table
  // needs its own in-flight flag — the panel-wide `loading` covers the first
  // render only, and reusing it here would blank the whole dashboard on a click.
  const [billingLoading, setBillingLoading] = useState(false)
  const [now] = useState(() => new Date())

  useEffect(() => {
    let active = true

    const load = async () => {
      setLoading(true)
      // The six widget requests go out together — the point of splitting the
      // old aggregated endpoint — and the panel renders once they have all
      // answered, so it never appears half-drawn.
      const [
        userResult,
        proyectosActivos,
        obligacionesProximas,
        tareasPendientes,
        clientesActivos,
        proximasObligaciones,
        facturacion,
      ] = await Promise.all([
        authApi.getCurrentUser().catch((error) => {
          console.error("[Strategos] Load current user error:", error)
          return null
        }),
        loadSection(dashboardApi.getActiveProjects),
        loadSection(dashboardApi.getUpcomingObligationsCount),
        loadSection(dashboardApi.getPendingTasks),
        loadSection(dashboardApi.getActiveCustomers),
        loadSection(dashboardApi.getUpcomingObligationsList),
        loadSection(() => dashboardApi.getBilling(1, BILLING_PAGE_SIZE)),
      ])

      if (!active) return

      setName(userResult?.success ? (userResult.user?.name ?? null) : null)

      const next: DashboardSections = {
        proyectosActivos,
        obligacionesProximas,
        tareasPendientes,
        clientesActivos,
        proximasObligaciones,
        facturacion,
      }

      // Every single widget failing points at the server or the session, not at
      // six independent Business Central sources going down at once — so say so
      // instead of listing all five as unavailable.
      if (Object.values(next).every((value) => value === null)) {
        setSections(null)
        setError("No se ha podido cargar el resumen.")
      } else {
        setSections(next)
        setError(null)
      }
      setLoading(false)
    }

    load()
    return () => {
      active = false
    }
  }, [])

  // Paging the billing table refetches that widget alone, leaving the rest of
  // the panel (and the initial spinner) untouched. The initial page already
  // came with the first load, so the first run is skipped.
  const isInitialBillingPage = useRef(true)
  useEffect(() => {
    if (isInitialBillingPage.current) {
      isInitialBillingPage.current = false
      return
    }

    let active = true
    setBillingLoading(true)
    loadSection(() => dashboardApi.getBilling(billingPage, BILLING_PAGE_SIZE)).then(
      (facturacion) => {
        // Stale responses are dropped, so clicking through pages quickly cannot
        // land an earlier page on top of a later one.
        if (!active) return
        setSections((prev) => (prev ? { ...prev, facturacion } : prev))
        setBillingLoading(false)
      },
    )

    return () => {
      active = false
    }
  }, [billingPage])

  // Greet by first name only ("Marc Solé" -> "Marc").
  const firstName = name?.trim().split(/\s+/)[0]
  const greeting = getGreeting(now.getHours())
  const missingSections = sections ? unavailableSections(sections) : []

  return (
    <div className="px-8 py-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">
          {greeting}
          {firstName ? `, ${firstName}` : ""}
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          {formatToday(now)} · resumen de la asesoría
        </p>
      </div>

      {loading ? (
        <div className="mt-16 flex items-center justify-center">
          <Loader2 className="size-8 animate-spin text-[#caa53d]" />
        </div>
      ) : !sections ? (
        <div className="mt-8 flex min-h-60 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-white px-6 text-center">
          <p className="text-sm text-slate-500">
            No se ha podido cargar el resumen.
          </p>
          {error && <p className="text-xs text-slate-400">{error}</p>}
        </div>
      ) : (
        <>
          {/* Some sections load while others don't (Business Central endpoints
              fail independently). Name what is missing, so a "—" is never
              mistaken for a real figure. */}
          {missingSections.length > 0 && (
            <Alert className="mt-6 border-amber-200 bg-amber-50 text-amber-900">
              <TriangleAlert />
              <AlertTitle>Información incompleta</AlertTitle>
              <AlertDescription className="text-amber-800">
                No se ha podido cargar desde Business Central:{" "}
                {missingSections.map(sectionLabel).join(", ")}.
              </AlertDescription>
            </Alert>
          )}

          <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile
              title="Proyectos activos"
              value={sections.proyectosActivos?.active ?? UNAVAILABLE}
              sublabel={
                sections.proyectosActivos
                  ? `de ${sections.proyectosActivos.total} totales`
                  : KPI_UNAVAILABLE
              }
            />
            <KpiTile
              title="Obligaciones próximas"
              value={sections.obligacionesProximas?.count ?? UNAVAILABLE}
              sublabel={
                sections.obligacionesProximas
                  ? "en los próximos 7 días"
                  : KPI_UNAVAILABLE
              }
              accent
            />
            <KpiTile
              title="Tareas pendientes"
              value={sections.tareasPendientes?.pending ?? UNAVAILABLE}
              sublabel={
                sections.tareasPendientes
                  ? `${sections.tareasPendientes.total} totales`
                  : KPI_UNAVAILABLE
              }
            />
            <KpiTile
              title="Clientes activos"
              value={sections.clientesActivos?.active ?? UNAVAILABLE}
              sublabel={
                sections.clientesActivos
                  ? `de ${sections.clientesActivos.total} totales`
                  : KPI_UNAVAILABLE
              }
            />
          </div>

          {/* Unified financial table, sourced live from Business Central: each
              customer groups its projects in an expandable accordion, paged so
              the panel stays compact. Sits right below the KPI tiles for a
              compact financial overview. */}
          <div className="mt-6">
            <FacturacionResumen
              groups={sections.facturacion?.items ?? null}
              meta={sections.facturacion?.meta ?? null}
              onPageChange={setBillingPage}
              isLoading={billingLoading}
            />
          </div>

          <div className="mt-6">
            <ProximasObligaciones obligations={sections.proximasObligaciones} />
          </div>
        </>
      )}
    </div>
  )
}
