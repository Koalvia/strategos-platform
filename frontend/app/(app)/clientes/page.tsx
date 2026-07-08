"use client"

import { useEffect, useState } from "react"

import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { customersApi } from "@/features/customers/api"
import { CustomersTable } from "@/features/customers/customers-table"
import type { Customer, CustomerStatus } from "@/lib/types"

type StatusFilter = "all" | CustomerStatus

export default function ClientesPage() {
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState<StatusFilter>("all")
  const [customers, setCustomers] = useState<Customer[]>([])
  const [loading, setLoading] = useState(true)

  // Debounce the search term so typing doesn't hit the backend on every keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState("")
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(handle)
  }, [search])

  useEffect(() => {
    let active = true

    const loadCustomers = async () => {
      setLoading(true)
      try {
        const result = await customersApi.getCustomers({
          search: debouncedSearch || undefined,
          status: status === "all" ? undefined : status,
        })
        if (!active) return
        setCustomers(result.success && result.data ? result.data : [])
      } catch (error) {
        console.error("[Strategos] Load customers error:", error)
        if (active) setCustomers([])
      } finally {
        if (active) setLoading(false)
      }
    }

    loadCustomers()
    return () => {
      active = false
    }
  }, [debouncedSearch, status])

  return (
    <div className="px-8 py-8">
      <h1 className="text-2xl font-bold text-slate-900">Clientes</h1>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <Input
          type="search"
          placeholder="Buscar cliente o NIF..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="h-11 bg-white sm:max-w-md"
        />
        <Select value={status} onValueChange={(value) => setStatus(value as StatusFilter)}>
          <SelectTrigger className="h-11 bg-white sm:w-56">
            <SelectValue placeholder="Todos" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Todos</SelectItem>
            <SelectItem value="Activo">Activo</SelectItem>
            <SelectItem value="Inactivo">Inactivo</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="mt-6">
        <CustomersTable customers={customers} loading={loading} />
      </div>
    </div>
  )
}
