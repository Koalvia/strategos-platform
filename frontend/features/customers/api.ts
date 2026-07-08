// Customers feature API client (client-side).
// Calls the Next.js route handler under /api/customers — never the backend directly.
import type { Customer, CustomerStatus } from "@/lib/types"

export interface GetCustomersParams {
  search?: string
  status?: CustomerStatus
}

export const customersApi = {
  async getCustomers(
    params: GetCustomersParams = {},
  ): Promise<{ success: boolean; data?: Customer[]; message?: string }> {
    const query = new URLSearchParams()
    if (params.search) query.set("search", params.search)
    if (params.status) query.set("status", params.status)
    const queryString = query.toString()

    const response = await fetch(`/api/customers${queryString ? `?${queryString}` : ""}`)
    return response.json()
  },
}
