// Customers feature API client (client-side).
// Calls the Next.js route handler under /api/customers — never the backend directly.
import type { Customer, CustomerPage, CustomerStatus } from "@/lib/types"

export interface GetCustomersParams {
  search?: string
  status?: CustomerStatus
  // Continuation token from a previous page's `nextCursor`; omit for page 1.
  cursor?: string
}

export const customersApi = {
  async getCustomers(
    params: GetCustomersParams = {},
  ): Promise<{ success: boolean; data?: CustomerPage; message?: string }> {
    const query = new URLSearchParams()
    if (params.search) query.set("search", params.search)
    if (params.status) query.set("status", params.status)
    if (params.cursor) query.set("cursor", params.cursor)
    const queryString = query.toString()

    const response = await fetch(`/api/customers${queryString ? `?${queryString}` : ""}`)
    return response.json()
  },

  async getCustomer(
    id: string,
  ): Promise<{ success: boolean; data?: Customer; message?: string }> {
    const response = await fetch(`/api/customers/${encodeURIComponent(id)}`)
    return response.json()
  },
}
