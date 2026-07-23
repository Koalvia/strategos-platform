"use client"

import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"

import { authApi } from "@/features/auth/api"
import { dashboardApi } from "@/features/dashboard/api"
import { FacturacionResumen } from "@/features/dashboard/facturacion-resumen"
import { KpiTile } from "@/features/dashboard/kpi-tile"
import { MisTareas } from "@/features/dashboard/mis-tareas"
import { ProximasObligaciones } from "@/features/dashboard/proximas-obligaciones"
import type { DashboardSummary } from "@/lib/types"

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
        setSummary(
          summaryResult.success && summaryResult.data ? summaryResult.data : null,
        )
      } catch (error) {
        console.error("[Strategos] Load dashboard error:", error)
        if (active) setSummary(null)
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
        <div className="mt-8 flex min-h-60 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white">
          <p className="text-sm text-slate-500">
            No se ha podido cargar el resumen.
          </p>
        </div>
      ) : (
        <>
          <div className="mt-6 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            <KpiTile
              title="Proyectos activos"
              value={summary.proyectosActivos.active}
              sublabel={`de ${summary.proyectosActivos.total} totales`}
            />
            <KpiTile
              title="Obligaciones próximas"
              value={summary.obligacionesProximas.count}
              sublabel="en los próximos 7 días"
              accent
            />
            <KpiTile
              title="Tareas pendientes"
              value={summary.tareasPendientes.pending}
              sublabel={`${summary.tareasPendientes.total} totales`}
            />
            <KpiTile
              title="Clientes activos"
              value={summary.clientesActivos.active}
              sublabel={`de ${summary.clientesActivos.total} totales`}
            />
          </div>

          {/* Unified financial table, sourced live from Business Central: each
              customer groups its projects in an expandable accordion. Sits right
              below the KPI tiles for a compact financial overview. */}
          <div className="mt-6">
            <FacturacionResumen groups={summary.facturacion} />
          </div>

          <div className="mt-6 grid gap-5 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <ProximasObligaciones obligations={summary.proximasObligaciones} />
            </div>
            <div>
              <MisTareas tasks={summary.misTareasDeHoy} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
