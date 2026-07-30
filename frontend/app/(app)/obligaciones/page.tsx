"use client"

import { type Dispatch, type SetStateAction, useEffect, useState } from "react"

import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { obligationsApi } from "@/features/obligations/api"
import { ObligationsTable } from "@/features/obligations/obligations-table"
import type {
  ObligationProjectOption,
  ObligationStatus,
  PageMeta,
  ProjectObligation,
} from "@/lib/types"

const ALL = "all"
const STATUS_OPTIONS: ObligationStatus[] = ["Vencido", "Al día", "Sin fecha"]

// Rows per page. A module constant rather than state: this screen has no
// rows-per-page selector, so it never needs to be reactive.
const PAGE_SIZE = 10

type StatusFilter = typeof ALL | ObligationStatus

export default function ObligacionesPage() {
  const [status, setStatus] = useState<StatusFilter>(ALL)
  const [projectId, setProjectId] = useState(ALL)
  const [page, setPage] = useState(1)
  const [obligations, setObligations] = useState<ProjectObligation[]>([])
  const [meta, setMeta] = useState<PageMeta | null>(null)
  const [loading, setLoading] = useState(true)
  const [projectOptions, setProjectOptions] = useState<ObligationProjectOption[]>([])

  useEffect(() => {
    let active = true

    const loadProjectOptions = async () => {
      try {
        const result = await obligationsApi.getProjectOptions()
        if (!active) return
        setProjectOptions(result.success && result.data ? result.data : [])
      } catch (error) {
        console.error("[Strategos] Load project options error:", error)
      }
    }

    loadProjectOptions()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    let active = true

    const loadObligations = async () => {
      setLoading(true)
      try {
        const result = await obligationsApi.getObligations({
          page,
          pageSize: PAGE_SIZE,
          status: status === ALL ? undefined : status,
          projectId: projectId === ALL ? undefined : projectId,
        })
        if (!active) return
        setObligations(result.success && result.data ? result.data : [])
        setMeta(result.success && result.meta ? result.meta : null)
      } catch (error) {
        console.error("[Strategos] Load obligations error:", error)
        if (active) {
          // Both, together: a stale meta over an empty table would paint a
          // pagination footer contradicting what is on screen.
          setObligations([])
          setMeta(null)
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    loadObligations()
    return () => {
      active = false
    }
  }, [page, status, projectId])

  // Any filter change goes back to page 1: page 3 of a shorter new result set
  // would show an empty table while matching rows exist.
  const handleFilterChange = <T,>(setter: Dispatch<SetStateAction<T>>, value: T) => {
    setter(value)
    setPage(1)
  }

  return (
    <div className="px-8 py-8">
      <h1 className="text-2xl font-bold text-slate-900">Obligaciones</h1>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs font-medium text-slate-500">Estado</Label>
          <Select
            value={status}
            onValueChange={(value) =>
              handleFilterChange(setStatus, value as StatusFilter)
            }
          >
            <SelectTrigger className="h-11 bg-white sm:w-44">
              <SelectValue placeholder="Todos" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Todos</SelectItem>
              {STATUS_OPTIONS.map((option) => (
                <SelectItem key={option} value={option}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs font-medium text-slate-500">Proyecto</Label>
          <Select
            value={projectId}
            onValueChange={(value) => handleFilterChange(setProjectId, value)}
          >
            <SelectTrigger className="h-11 bg-white sm:w-64">
              <SelectValue placeholder="Todos" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Todos</SelectItem>
              {projectOptions.map((option) => (
                <SelectItem key={option.id} value={option.id}>
                  {option.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="mt-6">
        <ObligationsTable
          obligations={obligations}
          loading={loading}
          meta={meta}
          onPageChange={setPage}
        />
      </div>
    </div>
  )
}
