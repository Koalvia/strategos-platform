"use client"

import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  settingsApi,
  type TrafficLightSettings,
} from "@/features/settings/api"

// Local editable copy of the thresholds. Kept as strings so the number inputs can
// be cleared while typing without collapsing to 0; parsed on save.
interface FormState {
  yellow: string
  red: string
  emailOnChange: boolean
}

function toFormState(settings: TrafficLightSettings): FormState {
  return {
    yellow: String(settings.yellow_within_days),
    red: String(settings.red_within_days),
    emailOnChange: settings.email_on_change_enabled,
  }
}

export function TrafficLightSettingsPanel() {
  const [form, setForm] = useState<FormState | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [saving, setSaving] = useState(false)
  // Set once a PUT is rejected with 403: the caller is not a director, so the
  // panel becomes read-only (the backend is the authoritative gate).
  const [readOnly, setReadOnly] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let active = true
    ;(async () => {
      setLoading(true)
      try {
        const result = await settingsApi.getTrafficLight()
        if (!active) return
        if (result.success && result.data) {
          setForm(toFormState(result.data))
          setLoadError(false)
        } else {
          setLoadError(true)
        }
      } catch (err) {
        if (!active) return
        console.error("[Strategos] Load traffic-light settings error:", err)
        setLoadError(true)
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const update = (patch: Partial<FormState>) => {
    setForm((prev) => (prev ? { ...prev, ...patch } : prev))
    setError(null)
    setSaved(false)
  }

  const save = async () => {
    if (!form) return

    const yellow = Number(form.yellow)
    const red = Number(form.red)

    if (!Number.isInteger(yellow) || !Number.isInteger(red)) {
      setError("Introduce números enteros de días.")
      return
    }
    // Mirror the backend rule (0 < red < yellow) so the common error surfaces
    // immediately instead of after a round-trip.
    if (!(red > 0 && red < yellow)) {
      setError(
        "El umbral rojo debe ser mayor que 0 y menor que el umbral amarillo.",
      )
      return
    }

    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const result = await settingsApi.updateTrafficLight({
        yellow_within_days: yellow,
        red_within_days: red,
        email_on_change_enabled: form.emailOnChange,
      })

      if (result.success && result.data) {
        setForm(toFormState(result.data))
        setSaved(true)
        return
      }

      if (result.status === 403) {
        setReadOnly(true)
        setError("Solo los directores pueden modificar estos valores.")
        return
      }

      if (result.status === 422) {
        setError(
          "Umbrales no válidos: el rojo debe ser mayor que 0 y menor que el amarillo.",
        )
        return
      }

      setError(result.message ?? "No se han podido guardar los cambios.")
    } catch (err) {
      console.error("[Strategos] Save traffic-light settings error:", err)
      setError("No se han podido guardar los cambios.")
    } finally {
      setSaving(false)
    }
  }

  const disabled = readOnly || saving

  return (
    <section className="mt-8 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">
          Semáforo de obligaciones
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          Días de antelación con los que una obligación pasa a amarillo o rojo, y
          el aviso por correo cuando una cambia de estado.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-10 text-slate-400">
          <Loader2 className="size-5 animate-spin" />
        </div>
      ) : loadError || !form ? (
        <p className="py-6 text-sm text-red-600">
          No se ha podido cargar la configuración del semáforo.
        </p>
      ) : (
        <div className="mt-6 flex flex-col gap-6">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-2">
              <Label htmlFor="yellow-within-days">Umbral amarillo (días)</Label>
              <Input
                id="yellow-within-days"
                type="number"
                min={1}
                value={form.yellow}
                disabled={disabled}
                onChange={(e) => update({ yellow: e.target.value })}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="red-within-days">Umbral rojo (días)</Label>
              <Input
                id="red-within-days"
                type="number"
                min={1}
                value={form.red}
                disabled={disabled}
                onChange={(e) => update({ red: e.target.value })}
              />
            </div>
          </div>

          <div className="flex items-center justify-between gap-4">
            <Label htmlFor="email-on-change" className="cursor-pointer">
              Avisar por correo cuando una obligación cambie de estado
            </Label>
            <Switch
              id="email-on-change"
              checked={form.emailOnChange}
              disabled={disabled}
              onCheckedChange={(checked) => update({ emailOnChange: checked })}
            />
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
          {saved && (
            <p className="text-sm text-green-600">Cambios guardados.</p>
          )}
          {readOnly && !error && (
            <p className="text-sm text-slate-500">
              Solo los directores pueden modificar estos valores.
            </p>
          )}

          <div className="flex justify-end">
            <Button onClick={save} disabled={disabled}>
              {saving && <Loader2 className="size-4 animate-spin" />}
              Guardar cambios
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
