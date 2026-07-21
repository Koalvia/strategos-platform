// Alerts feature API client (client-side).
// Calls the Next.js route handlers under /api/alerts — never the backend directly.

// An alert's lifecycle status. Mirrors the backend `AlertStatus` enum values.
// UI copy: new = "Sin leer", viewed = "Vistas", discarded = "Descartadas".
export type AlertStatus = "new" | "viewed" | "discarded"

// The source that raised the alert. Mirrors the backend `AlertType` enum values.
export type AlertType = "BOPA" | "OBLIGATION"

// A single alert as returned by the backend. Fields mirror the backend
// `AlertResponse` schema (snake_case). `title`/`message` are unified display
// fields for either type; the remaining fields are BOPA-specific (null for
// OBLIGATION alerts, whose display comes from title/message).
export interface Alert {
  id: number
  customer_id: string
  alert_type: AlertType
  status: AlertStatus
  created_at: string | null
  title: string | null
  message: string | null
  matched_term: string | null
  document_id: number | null
  document_title: string | null
  article_date: string | null
  source_url: string | null
}

export interface AlertPage {
  items: Alert[]
  total: number
}

export interface GetAlertsParams {
  status?: AlertStatus
  limit?: number
  offset?: number
}

export const alertsApi = {
  async getAlerts(
    params: GetAlertsParams = {},
  ): Promise<{ success: boolean; data?: AlertPage; message?: string }> {
    const query = new URLSearchParams()
    if (params.status) query.set("status", params.status)
    if (params.limit !== undefined) query.set("limit", String(params.limit))
    if (params.offset !== undefined) query.set("offset", String(params.offset))
    const queryString = query.toString()

    const response = await fetch(`/api/alerts${queryString ? `?${queryString}` : ""}`)
    return response.json()
  },

  async getUnreadCount(): Promise<{
    success: boolean
    data?: { count: number }
    message?: string
  }> {
    const response = await fetch("/api/alerts/unread-count")
    return response.json()
  },

  async updateStatus(
    id: number,
    status: AlertStatus,
  ): Promise<{ success: boolean; data?: Alert; message?: string }> {
    const response = await fetch(`/api/alerts/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    })
    return response.json()
  },

  async markAllRead(): Promise<{
    success: boolean
    data?: { updated: number }
    message?: string
  }> {
    const response = await fetch("/api/alerts/mark-all-read", { method: "POST" })
    return response.json()
  },
}
