// Obligations feature API client (client-side).
// Calls the Next.js route handler under /api/obligations — never the backend
// directly.
import { config } from "@/lib/config"
import type {
  ObligationProjectOption,
  ObligationStatus,
  PageMeta,
  ProjectObligation,
} from "@/lib/types"

export interface GetObligationsParams {
  status?: ObligationStatus
  projectId?: string
  dueAfter?: string
  dueBefore?: string
  page?: number
  // Omitting it means "every match in one page" — a supported choice, not an
  // oversight. Do not give it a default: it would silently truncate the callers
  // that need the complete list.
  pageSize?: number
}

export const obligationsApi = {
  async getObligations(params: GetObligationsParams = {}): Promise<{
    success: boolean
    data?: ProjectObligation[]
    // Present when a page was requested; drives the table's pagination footer.
    meta?: PageMeta
    message?: string
  }> {
    const query = new URLSearchParams()
    if (params.status) query.set("status", params.status)
    if (params.projectId) query.set("project_id", params.projectId)
    if (params.dueAfter) query.set("due_after", params.dueAfter)
    if (params.dueBefore) query.set("due_before", params.dueBefore)
    if (params.page) query.set("page", String(params.page))
    if (params.pageSize) query.set("page_size", String(params.pageSize))
    const queryString = query.toString()

    const response = await fetch(
      `${config.api.endpoints.obligations.base}${queryString ? `?${queryString}` : ""}`,
    )
    return response.json()
  },

  // The distinct projects that have obligations, name-ordered by the backend.
  // Independent of the table's filters and page, so the options never shrink to
  // whatever is on screen.
  async getProjectOptions(): Promise<{
    success: boolean
    data?: ObligationProjectOption[]
    message?: string
  }> {
    const response = await fetch(config.api.endpoints.obligations.projectOptions)
    return response.json()
  },
}
