"use client"

import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
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
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [noAssignedCustomers, setNoAssignedCustomers] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)

  // Debounce the search term so typing doesn't hit the backend on every keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState("")
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(handle)
  }, [search])

  // Whenever the search/status filters change, restart pagination from page 1.
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
        if (result.success && result.data) {
          setCustomers(result.data.items)
          setNextCursor(result.data.nextCursor)
          setNoAssignedCustomers(result.data.noAssignedCustomers)
        } else {
          setCustomers([])
          setNextCursor(null)
        }
      } catch (error) {
        console.error("[Strategos] Load customers error:", error)
        if (active) {
          setCustomers([])
          setNextCursor(null)
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    loadCustomers()
    return () => {
      active = false
    }
  }, [debouncedSearch, status])

  const handleLoadMore = async () => {
    if (!nextCursor) return
    setLoadingMore(true)
    try {
      const result = await customersApi.getCustomers({
        search: debouncedSearch || undefined,
        status: status === "all" ? undefined : status,
        cursor: nextCursor,
      })
      if (result.success && result.data) {
        setCustomers((prev) => [...prev, ...result.data!.items])
        setNextCursor(result.data.nextCursor)
      }
    } catch (error) {
      console.error("[Strategos] Load more customers error:", error)
    } finally {
      setLoadingMore(false)
    }
  }

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
        <CustomersTable
          customers={customers}
          loading={loading}
          noAssignedCustomers={noAssignedCustomers}
        />
      </div>

      {!loading && nextCursor && (
        <div className="mt-4 flex justify-center">
          <Button variant="outline" onClick={handleLoadMore} disabled={loadingMore}>
            {loadingMore ? "Cargando..." : "Cargar más"}
          </Button>
        </div>
      )}
    </div>
  )
}
