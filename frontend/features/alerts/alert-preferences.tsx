"use client"

import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"

import { Switch } from "@/components/ui/switch"
import {
  alertsApi,
  type AlertCategory,
  type AlertPreference,
} from "@/features/alerts/api"

// Spanish label for each notification category, in display order.
const CATEGORY_LABEL: { category: AlertCategory; label: string }[] = [
  { category: "BOPA", label: "Publicaciones BOPA" },
  { category: "DOCUMENT_EXPIRY", label: "Caducidad de DNI / pasaporte" },
  { category: "IVA", label: "Presentación de IVA" },
  { category: "OBLIGATION", label: "Otras obligaciones y vencimientos" },
]

export function AlertPreferencesPanel() {
  const [prefs, setPrefs] = useState<Record<string, boolean>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<AlertCategory | null>(null)

  useEffect(() => {
    let active = true
    alertsApi.getPreferences().then((res) => {
      if (!active) return
      if (res.success && res.data) {
        setPrefs(
          Object.fromEntries(
            res.data.items.map((p: AlertPreference) => [p.category, p.email_enabled]),
          ),
        )
      }
      setLoading(false)
    })
    return () => {
      active = false
    }
  }, [])

  const toggle = async (category: AlertCategory, next: boolean) => {
    setSaving(category)
    // Optimistic; reconcile from the server response.
    setPrefs((p) => ({ ...p, [category]: next }))
    const res = await alertsApi.updatePreference(category, next)
    if (res.success && res.data) {
      setPrefs(
        Object.fromEntries(res.data.items.map((p) => [p.category, p.email_enabled])),
      )
    }
    setSaving(null)
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="text-sm font-semibold text-slate-900">Avisos por email</h2>
      <p className="mt-1 text-sm text-slate-500">
        Elige de qué quieres recibir aviso por correo. Solo llegan los avisos de tus
        clientes asignados.
      </p>
      {loading ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" /> Cargando…
        </div>
      ) : (
        <div className="mt-4 flex flex-col divide-y divide-slate-100">
          {CATEGORY_LABEL.map(({ category, label }) => (
            <div
              key={category}
              className="flex items-center justify-between py-3"
            >
              <span className="text-sm text-slate-700">{label}</span>
              <Switch
                checked={prefs[category] ?? true}
                disabled={saving === category}
                onCheckedChange={(next) => toggle(category, next)}
                aria-label={label}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
