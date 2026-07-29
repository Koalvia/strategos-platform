// Dashboard feature API client (client-side).
// Calls the Next.js route handlers under /api/dashboard — never the backend
// directly. One call per widget, so the page loads them in parallel and a slow
// or failing widget never blocks the others.
import { config } from "@/lib/config"
import type {
  ActiveTotalKpi,
  ApiResponse,
  CountKpi,
  CustomerBillingPage,
  PendingTotalKpi,
  ProjectObligation,
} from "@/lib/types"

export type { ActiveTotalKpi, PendingTotalKpi, CountKpi }

const routes = config.api.endpoints.dashboard

// Every widget can come back as `data: null` when Business Central could not
// serve it — distinct from an empty list, and rendered as "No disponible".
export const dashboardApi = {
  async getActiveProjects(): Promise<ApiResponse<ActiveTotalKpi | null>> {
    const response = await fetch(routes.activeProjects)
    return response.json()
  },

  async getActiveCustomers(): Promise<ApiResponse<ActiveTotalKpi | null>> {
    const response = await fetch(routes.activeCustomers)
    return response.json()
  },

  async getPendingTasks(): Promise<ApiResponse<PendingTotalKpi | null>> {
    const response = await fetch(routes.pendingTasks)
    return response.json()
  },

  async getUpcomingObligationsCount(): Promise<ApiResponse<CountKpi | null>> {
    const response = await fetch(routes.upcomingObligationsCount)
    return response.json()
  },

  async getUpcomingObligationsList(): Promise<ApiResponse<ProjectObligation[] | null>> {
    const response = await fetch(routes.obligations)
    return response.json()
  },

  async getBilling(
    page = 1,
    pageSize = 10,
  ): Promise<ApiResponse<CustomerBillingPage | null>> {
    const query = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    })
    const response = await fetch(`${routes.billing}?${query}`)
    return response.json()
  },
}
