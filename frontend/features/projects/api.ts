// Projects feature API client (client-side).
// Calls the Next.js route handlers under /api/projects and /api/obligations —
// never the backend directly.
import type { Project, ProjectObligation, ProjectPage, ProjectStatus } from "@/lib/types"

export interface GetProjectsParams {
  search?: string
  projectType?: string
  entityType?: string
  status?: ProjectStatus
  // Restrict to a single customer's projects (used by the customer detail screen).
  customerId?: string
  // Continuation token from a previous page's `nextCursor`; omit for page 1.
  cursor?: string
}

export const projectsApi = {
  async getProjects(
    params: GetProjectsParams = {},
  ): Promise<{ success: boolean; data?: ProjectPage; message?: string }> {
    const query = new URLSearchParams()
    if (params.search) query.set("search", params.search)
    if (params.projectType) query.set("project_type", params.projectType)
    if (params.entityType) query.set("entity_type", params.entityType)
    if (params.status) query.set("status", params.status)
    if (params.customerId) query.set("customer_id", params.customerId)
    if (params.cursor) query.set("cursor", params.cursor)
    const queryString = query.toString()

    const response = await fetch(`/api/projects${queryString ? `?${queryString}` : ""}`)
    return response.json()
  },

  async getProject(
    id: string,
  ): Promise<{ success: boolean; data?: Project; message?: string }> {
    const response = await fetch(`/api/projects/${encodeURIComponent(id)}`)
    return response.json()
  },

  async getObligations(): Promise<{
    success: boolean
    data?: ProjectObligation[]
    message?: string
  }> {
    const response = await fetch("/api/obligations")
    return response.json()
  },
}
