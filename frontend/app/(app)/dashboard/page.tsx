"use client"

import { useEffect, useState } from "react"
import { TriangleAlert } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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

interface LoadingSections {
  proyectosActivos: boolean
  obligacionesProximas: boolean
  tareasPendientes: boolean
  clientesActivos: boolean
  proximasObligaciones: boolean
  facturacion: boolean
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
function unavailableSections(
  sections: DashboardSections,
  loading: LoadingSections
): string[] {
  const missing: string[] = []
  if (!loading.clientesActivos && sections.clientesActivos === null) missing.push("customers")
  if (!loading.proyectosActivos && sections.proyectosActivos === null) missing.push("projects")
  if (!loading.tareasPendientes && sections.tareasPendientes === null) missing.push("tasks")
  // Both obligation widgets read the same source, so they name it once.
  if (
    !loading.obligacionesProximas &&
    !loading.proximasObligaciones &&
    (sections.obligacionesProximas === null || sections.proximasObligaciones === null)
  ) {
    missing.push("obligations")
  }
  if (!loading.facturacion && sections.facturacion === null) missing.push("billing")
  return missing
}

export default function DashboardPage() {
  const [sections, setSections] = useState<DashboardSections>({
    proyectosActivos: null,
    obligacionesProximas: null,
    tareasPendientes: null,
    clientesActivos: null,
    proximasObligaciones: null,
    facturacion: null,
  })
  const [loading, setLoading] = useState<LoadingSections>({
    proyectosActivos: true,
    obligacionesProximas: true,
    tareasPendientes: true,
    clientesActivos: true,
    proximasObligaciones: true,
    facturacion: true,
  })
  // Paging billing hits Business Central for that page's customers, so it is not
  // instant: the table reuses `loading.facturacion` to dim itself on a click.
  const [billingPage, setBillingPage] = useState(1)
  const [now] = useState(() => new Date())

  useEffect(() => {
    let active = true
    //Helper to refresh isolated widgets
    const fetchWidget = <k extends keyof DashboardSections>(
      key: k,
      apiCall: () => Promise<ApiResponse<DashboardSections[k] | null>>
    ) => {
      loadSection(apiCall).then((data) => {
        if (!active) return
        setSections((prev) => ({ ...prev, [key]: data }))
        setLoading((prev) => ({ ...prev, [key]: false }))
      })
    }

    //independent widgets render
    fetchWidget("proyectosActivos", dashboardApi.getActiveProjects)
    fetchWidget("obligacionesProximas", dashboardApi.getUpcomingObligationsCount)
    fetchWidget("tareasPendientes", dashboardApi.getPendingTasks)
    fetchWidget("clientesActivos", dashboardApi.getActiveCustomers)
    fetchWidget("proximasObligaciones", dashboardApi.getUpcomingObligationsList)
    // Billing is deliberately absent here: the `billingPage` effect below owns
    // it for both the first load and every page change. Fetching it in both
    // places would issue two live Business Central reads for page 1.

    return () => {
      active = false
    }
  }, [])

  // Billing table: initial load and pagination. Isolated from the widgets above
  // so paging re-reads only this section.

  useEffect(() => {
    let active = true
    setLoading((prev) => ({ ...prev, facturacion: true }))

    loadSection(() => dashboardApi.getBilling(billingPage, BILLING_PAGE_SIZE)).then(
      (facturacion) => {
        // Stale responses are dropped, so clicking through pages quickly cannot
        // land an earlier page on top of a later one.
        if (!active) return
        setSections((prev) => ({ ...prev, facturacion }))
        setLoading((prev) => ({ ...prev, facturacion: false }))
      },
    )

    return () => {
      active = false
    }
  }, [billingPage])

  const greeting = getGreeting(now.getHours())
  const missingSections = unavailableSections(sections, loading)
  const isAnyLoading = Object.values(loading).some(Boolean)

  return (
    <div className="px-8 py-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">{greeting}</h1>
        <p className="mt-1 text-sm text-slate-500">
          {formatToday(now)} · resumen de la asesoría
        </p>
      </div>

      {/* . Pending widgets render their own placeholder. 
       Some sections load while others don't (Business Central endpoints fail
      independently). Held back until every widget has settled, so the notice
          appears once, complete, rather than growing section by section. */}
      {missingSections.length > 0 && !isAnyLoading && (
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
          isLoading={loading.proyectosActivos}
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
          isLoading={loading.obligacionesProximas}
        />
        <KpiTile
          title="Tareas pendientes"
          value={sections.tareasPendientes?.pending ?? UNAVAILABLE}
          sublabel={
            sections.tareasPendientes
              ? `${sections.tareasPendientes.total} totales`
              : KPI_UNAVAILABLE
          }
          isLoading={loading.tareasPendientes}
        />
        <KpiTile
          title="Clientes activos"
          value={sections.clientesActivos?.active ?? UNAVAILABLE}
          sublabel={
            sections.clientesActivos
              ? `de ${sections.clientesActivos.total} totales`
              : KPI_UNAVAILABLE
          }
          isLoading={loading.clientesActivos}
        />
      </div>

      <div className="mt-6">
        <FacturacionResumen
          groups={sections.facturacion?.items ?? null}
          meta={sections.facturacion?.meta ?? null}
          onPageChange={setBillingPage}
          isLoading={loading.facturacion}
        />
      </div>

      <div className="mt-6">
        <ProximasObligaciones
          obligations={sections.proximasObligaciones}
          isLoading={loading.proximasObligaciones}
        />
      </div>
    </div>
  )
}
