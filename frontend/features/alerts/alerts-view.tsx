"use client"

import { useCallback, useEffect, useState } from "react"
import { ExternalLink, Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { alertsApi, type Alert, type AlertStatus } from "@/features/alerts/api"

// Spanish label for each alert source, shown as a small badge on every row.
const ALERT_TYPE_LABEL: Record<Alert["alert_type"], string> = {
  BOPA: "BOPA",
  OBLIGATION: "Obligación",
}

// Tabs mirror the alert lifecycle. UI copy is Spanish to match the rest of the app.
const TABS: { value: AlertStatus; label: string }[] = [
  { value: "new", label: "Sin leer" },
  { value: "viewed", label: "Vistas" },
  { value: "discarded", label: "Descartadas" },
]

function formatDate(value: string | null): string {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "—"
  return date.toLocaleDateString("es-ES", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  })
}

// Notify the sidebar so its unread badge refreshes right after a mutation.
function notifyAlertsChanged() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("alerts:changed"))
  }
}

export function AlertsView() {
  const [status, setStatus] = useState<AlertStatus>("new")
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [markingAll, setMarkingAll] = useState(false)

  const loadAlerts = useCallback(async () => {
    setLoading(true)
    try {
      const result = await alertsApi.getAlerts({ status, limit: 100 })
      if (result.success && result.data) {
        setAlerts(result.data.items)
      } else {
        setAlerts([])
      }
    } catch (error) {
      console.error("[Strategos] Load alerts error:", error)
      setAlerts([])
    } finally {
      setLoading(false)
    }
  }, [status])

  useEffect(() => {
    loadAlerts()
  }, [loadAlerts])

  const changeStatus = async (id: number, next: AlertStatus) => {
    setBusyId(id)
    try {
      const result = await alertsApi.updateStatus(id, next)
      if (result.success) {
        await loadAlerts()
        notifyAlertsChanged()
      }
    } catch (error) {
      console.error("[Strategos] Update alert error:", error)
    } finally {
      setBusyId(null)
    }
  }

  const markAllRead = async () => {
    setMarkingAll(true)
    try {
      const result = await alertsApi.markAllRead()
      if (result.success) {
        await loadAlerts()
        notifyAlertsChanged()
      }
    } catch (error) {
      console.error("[Strategos] Mark all alerts read error:", error)
    } finally {
      setMarkingAll(false)
    }
  }

  return (
    <div className="px-8 py-8">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Alertas</h1>
          <p className="mt-1 text-sm text-slate-500">
            Notificaciones del BOPA y obligaciones de Business Central.
          </p>
        </div>
        {status === "new" && (
          <Button
            variant="outline"
            onClick={markAllRead}
            disabled={markingAll || alerts.length === 0}
          >
            Marcar todas como leídas
          </Button>
        )}
      </div>

      <Tabs
        value={status}
        onValueChange={(value) => setStatus(value as AlertStatus)}
        className="mt-6"
      >
        <TabsList>
          {TABS.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {TABS.map((tab) => (
          <TabsContent key={tab.value} value={tab.value} className="mt-4">
            {loading ? (
              <div className="flex items-center justify-center py-16 text-slate-400">
                <Loader2 className="size-6 animate-spin" />
              </div>
            ) : alerts.length === 0 ? (
              <p className="py-16 text-center text-sm text-slate-500">
                No hay alertas en esta categoría.
              </p>
            ) : (
              <ul className="flex flex-col gap-3">
                {alerts.map((alert) => (
                  <li
                    key={alert.id}
                    className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
                  >
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <Badge
                            variant="secondary"
                            className="shrink-0 text-[10px] uppercase tracking-wide"
                          >
                            {ALERT_TYPE_LABEL[alert.alert_type]}
                          </Badge>
                          <p className="truncate text-sm font-semibold text-slate-900">
                            {alert.title ?? alert.customer_id}
                          </p>
                        </div>
                        {alert.alert_type === "OBLIGATION" ? (
                          <p className="mt-0.5 truncate text-sm text-slate-600">
                            {alert.message ?? "Obligación"}
                          </p>
                        ) : (
                          <>
                            <p className="mt-0.5 truncate text-sm text-slate-600">
                              {alert.document_title ?? "Documento del BOPA"}
                            </p>
                            <p className="mt-1 text-xs text-slate-400">
                              {formatDate(alert.article_date)}
                              {alert.source_url && (
                                <>
                                  {" · "}
                                  <a
                                    href={alert.source_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="inline-flex items-center gap-1 text-[#caa53d] hover:underline"
                                  >
                                    Ver documento
                                    <ExternalLink className="size-3" />
                                  </a>
                                </>
                              )}
                            </p>
                          </>
                        )}
                      </div>

                      <div className="flex shrink-0 items-center gap-2">
                        {alert.status === "new" && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={busyId === alert.id}
                            onClick={() => changeStatus(alert.id, "viewed")}
                          >
                            Marcar como vista
                          </Button>
                        )}
                        {alert.status !== "discarded" && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-slate-500 hover:text-red-600"
                            disabled={busyId === alert.id}
                            onClick={() => changeStatus(alert.id, "discarded")}
                          >
                            Descartar
                          </Button>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}
