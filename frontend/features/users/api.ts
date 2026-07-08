// Users feature API client (client-side).
// Calls the Next.js route handler under /api/users — never the backend directly.
import type { UserDirectoryEntry } from "@/lib/types"

export const usersApi = {
  async getUsers(): Promise<{ success: boolean; data?: UserDirectoryEntry[]; message?: string }> {
    const response = await fetch("/api/users")
    return response.json()
  },
}
