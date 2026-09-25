// Settings feature API client (client-side).
// Calls the Next.js route handlers under /api/settings — never the backend directly.

// The obligations traffic-light thresholds. Fields mirror the backend
// `TrafficLightSettingsResponse` schema (snake_case). `yellow_within_days` is the
// green→yellow boundary and `red_within_days` the yellow→red one; the backend
// enforces `0 < red_within_days < yellow_within_days`.
export interface TrafficLightSettings {
  yellow_within_days: number
  red_within_days: number
  email_on_change_enabled: boolean
  updated_at: string | null
}

// The editable subset sent on a full-replacement PUT.
export interface TrafficLightSettingsUpdate {
  yellow_within_days: number
  red_within_days: number
  email_on_change_enabled: boolean
}

// Result envelope carrying the HTTP status so callers can tell a 403 (non-director)
// from a 422 (invalid thresholds) and react accordingly.
interface SettingsResult<T> {
  success: boolean
  status: number
  data?: T
  message?: string
}

async function parse<T>(response: Response): Promise<SettingsResult<T>> {
  const body = await response.json().catch(() => ({}))
  return {
    success: Boolean(body.success),
    status: response.status,
    data: body.data,
    message: body.message,
  }
}

export const settingsApi = {
  async getTrafficLight(): Promise<SettingsResult<TrafficLightSettings>> {
    const response = await fetch("/api/settings/traffic-light")
    return parse<TrafficLightSettings>(response)
  },

  async updateTrafficLight(
    data: TrafficLightSettingsUpdate,
  ): Promise<SettingsResult<TrafficLightSettings>> {
    const response = await fetch("/api/settings/traffic-light", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    })
    return parse<TrafficLightSettings>(response)
  },
}
