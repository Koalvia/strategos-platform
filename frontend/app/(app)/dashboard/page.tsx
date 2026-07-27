"use client"

import { useEffect, useState } from "react"
import { Loader2, TriangleAlert } from "lucide-react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { authApi } from "@/features/auth/api"
import { dashboardApi } from "@/features/dashboard/api"
import { FacturacionResumen } from "@/features/dashboard/facturacion-resumen"
import { UNAVAILABLE } from "@/features/dashboard/format"
import { KpiTile } from "@/features/dashboard/kpi-tile"
import { ProximasObligaciones } from "@/features/dashboard/proximas-obligaciones"
import type { DashboardSummary } from "@/lib/types"

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

export default function DashboardPage() {
  const [name, setName] = useState<string | null>(null)
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  // Why the summary is missing, when it is. Kept separate from `summary` so a
  // failed load is distinguishable from a summary that legitimately has no data.
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [now] = useState(() => new Date())

  useEffect(() => {
    let active = true

    const load = async () => {
      setLoading(true)
      try {
        const [userResult, summaryResult] = await Promise.all([
          authApi.getCurrentUser(),
          dashboardApi.getSummary(),
        ])
        if (!active) return
        setName(userResult.success ? (userResult.user?.name ?? null) : null)
        if (summaryResult.success && summaryResult.data) {
          setSummary(summaryResult.data)
          setError(null)
        } else {
          setSummary(null)
          // Surface the backend's own message instead of discarding it — it is
          // what makes a real failure diagnosable from the UI.
          setError(summaryResult.message ?? "No se ha podido cargar el resumen.")
        }
      } catch (error) {
        console.error("[Strategos] Load dashboard error:", error)
        if (active) {
          setSummary(null)
          setError("No se ha podido conectar con el servidor.")
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    load()
    return () => {
      active = false
    }
  }, [])

  // Greet by first name only ("Marc Solé" -> "Marc").
  const firstName = name?.trim().split(/\s+/)[0]
  const greeting = getGreeting(now.getHours())

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
      ) : !summary ? (
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
          {summary.unavailableSections.length > 0 && (
            <Alert className="mt-6 border-amber-200 bg-amber-50 text-amber-900">
              <TriangleAlert />
              <AlertTitle>Información incompleta</AlertTitle>
              <AlertDescription className="text-amber-800">
                No se ha podido cargar desde Business Central:{" "}
                {summary.unavailableSections.map(sectionLabel).join(", ")}.
              </AlertDescription>
            </Alert>
          )}

          <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile
              title="Proyectos activos"
              value={summary.proyectosActivos?.active ?? UNAVAILABLE}
              sublabel={
                summary.proyectosActivos
                  ? `de ${summary.proyectosActivos.total} totales`
                  : KPI_UNAVAILABLE
              }
            />
            <KpiTile
              title="Obligaciones próximas"
              value={summary.obligacionesProximas?.count ?? UNAVAILABLE}
              sublabel={
                summary.obligacionesProximas
                  ? "en los próximos 7 días"
                  : KPI_UNAVAILABLE
              }
              accent
            />
            <KpiTile
              title="Tareas pendientes"
              value={summary.tareasPendientes?.pending ?? UNAVAILABLE}
              sublabel={
                summary.tareasPendientes
                  ? `${summary.tareasPendientes.total} totales`
                  : KPI_UNAVAILABLE
              }
            />
            <KpiTile
              title="Clientes activos"
              value={summary.clientesActivos?.active ?? UNAVAILABLE}
              sublabel={
                summary.clientesActivos
                  ? `de ${summary.clientesActivos.total} totales`
                  : KPI_UNAVAILABLE
              }
            />
          </div>

          {/* Unified financial table, sourced live from Business Central: each
              customer groups its projects in an expandable accordion. Sits right
              below the KPI tiles for a compact financial overview. */}
          <div className="mt-6">
            <FacturacionResumen groups={summary.facturacion} />
          </div>

          <div className="mt-6">
            <ProximasObligaciones obligations={summary.proximasObligaciones} />
          </div>
        </>
      )}
    </div>
  )
}
