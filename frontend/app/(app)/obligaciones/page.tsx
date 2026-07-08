"use client"

import { useEffect, useMemo, useState } from "react"

import { Input } from "@/components/ui/input"
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
import type { ObligationStatus, ProjectObligation } from "@/lib/types"

const ALL = "all"
const STATUS_OPTIONS: ObligationStatus[] = ["Vencido", "Próximo", "Al día"]

type StatusFilter = typeof ALL | ObligationStatus

export default function ObligacionesPage() {
  const [status, setStatus] = useState<StatusFilter>(ALL)
  const [projectId, setProjectId] = useState(ALL)
  const [dueAfter, setDueAfter] = useState("")
  const [dueBefore, setDueBefore] = useState("")
  const [obligations, setObligations] = useState<ProjectObligation[]>([])
  const [loading, setLoading] = useState(true)

  // Project filter options come from a one-time unfiltered fetch so narrowing
  // the list never shrinks the option list.
  const [allObligations, setAllObligations] = useState<ProjectObligation[]>([])

  const projectOptions = useMemo(() => {
    const byId = new Map<string, string>()
    for (const obligation of allObligations) {
      byId.set(obligation.project.id, obligation.project.name)
    }
    return Array.from(byId, ([id, name]) => ({ id, name })).sort((a, b) =>
      a.name.localeCompare(b.name),
    )
  }, [allObligations])

  useEffect(() => {
    let active = true

    const loadOnce = async () => {
      try {
        const result = await obligationsApi.getObligations()
        if (!active) return
        setAllObligations(result.success && result.data ? result.data : [])
      } catch (error) {
        console.error("[Strategos] Load obligations metadata error:", error)
      }
    }

    loadOnce()
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
          status: status === ALL ? undefined : status,
          projectId: projectId === ALL ? undefined : projectId,
          dueAfter: dueAfter || undefined,
          dueBefore: dueBefore || undefined,
        })
        if (!active) return
        setObligations(result.success && result.data ? result.data : [])
      } catch (error) {
        console.error("[Strategos] Load obligations error:", error)
        if (active) setObligations([])
      } finally {
        if (active) setLoading(false)
      }
    }

    loadObligations()
    return () => {
      active = false
    }
  }, [status, projectId, dueAfter, dueBefore])

  return (
    <div className="px-8 py-8">
      <h1 className="text-2xl font-bold text-slate-900">Obligaciones</h1>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs font-medium text-slate-500">Estado</Label>
          <Select value={status} onValueChange={(value) => setStatus(value as StatusFilter)}>
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
          <Select value={projectId} onValueChange={setProjectId}>
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

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs font-medium text-slate-500">Desde</Label>
          <Input
            type="date"
            value={dueAfter}
            onChange={(event) => setDueAfter(event.target.value)}
            className="h-11 bg-white sm:w-44"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label className="text-xs font-medium text-slate-500">Hasta</Label>
          <Input
            type="date"
            value={dueBefore}
            onChange={(event) => setDueBefore(event.target.value)}
            className="h-11 bg-white sm:w-44"
          />
        </div>
      </div>

      <div className="mt-6">
        <ObligationsTable obligations={obligations} loading={loading} />
      </div>
    </div>
  )
}
