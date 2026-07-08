"use client"

import { useEffect, useState } from "react"

import { usersApi } from "@/features/users/api"
import { UsersTable } from "@/features/users/users-table"
import type { UserDirectoryEntry } from "@/lib/types"

export default function UsuariosPage() {
  const [users, setUsers] = useState<UserDirectoryEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true

    const loadUsers = async () => {
      setLoading(true)
      try {
        const result = await usersApi.getUsers()
        if (!active) return
        setUsers(result.success && result.data ? result.data : [])
      } catch (error) {
        console.error("[Strategos] Load users error:", error)
        if (active) setUsers([])
      } finally {
        if (active) setLoading(false)
      }
    }

    loadUsers()
    return () => {
      active = false
    }
  }, [])

  return (
    <div className="px-8 py-8">
      <h1 className="text-2xl font-bold text-slate-900">Usuarios</h1>

      <div className="mt-6">
        <UsersTable users={users} loading={loading} />
      </div>
    </div>
  )
}
