// Obligations feature API client (client-side).
// Calls the Next.js route handler under /api/obligations — never the backend
// directly.
import type { ObligationStatus, ProjectObligation } from "@/lib/types"

export interface GetObligationsParams {
  status?: ObligationStatus
  projectId?: string
  dueAfter?: string
  dueBefore?: string
}

export const obligationsApi = {
  async getObligations(
    params: GetObligationsParams = {},
  ): Promise<{ success: boolean; data?: ProjectObligation[]; message?: string }> {
    const query = new URLSearchParams()
    if (params.status) query.set("status", params.status)
    if (params.projectId) query.set("project_id", params.projectId)
    if (params.dueAfter) query.set("due_after", params.dueAfter)
    if (params.dueBefore) query.set("due_before", params.dueBefore)
    const queryString = query.toString()

    const response = await fetch(
      `/api/obligations${queryString ? `?${queryString}` : ""}`,
    )
    return response.json()
  },
}
