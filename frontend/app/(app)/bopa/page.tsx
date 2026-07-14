"use client"

import { useEffect, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { bopaApi, type BopaDocument, type BopaFilterOptions } from "@/features/bopa/api"
import { BopaTable } from "@/features/bopa/bopa-table"

const ALL = "all"
const PAGE_SIZE = 20

const EMPTY_FILTERS: BopaFilterOptions = {
  organisme: [],
  tema: [],
  organisme_pare: [],
  tema_pare: [],
}

export default function BopaPage() {
  const [search, setSearch] = useState("")
  const [organisme, setOrganisme] = useState(ALL)
  const [tema, setTema] = useState(ALL)
  const [organismePare, setOrganismePare] = useState(ALL)
  const [temaPare, setTemaPare] = useState(ALL)
  const [year, setYear] = useState("")
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")

  const [documents, setDocuments] = useState<BopaDocument[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)

  const [filterOptions, setFilterOptions] = useState<BopaFilterOptions>(EMPTY_FILTERS)

  // Debounce the free-text title search so typing doesn't hit the backend on
  // every keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState("")
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(handle)
  }, [search])

  // Load the facet dropdown values once.
  useEffect(() => {
    let active = true
    const loadFilters = async () => {
      try {
        const result = await bopaApi.getFilterOptions()
        if (active && result.success && result.data) setFilterOptions(result.data)
      } catch (error) {
        console.error("[Strategos] Load BOPA filter options error:", error)
      }
    }
    loadFilters()
    return () => {
      active = false
    }
  }, [])

  // Reset to page 1 whenever any filter changes.
  useEffect(() => {
    setPage(0)
  }, [debouncedSearch, organisme, tema, organismePare, temaPare, year, dateFrom, dateTo])

  useEffect(() => {
    let active = true

    const loadDocuments = async () => {
      setLoading(true)
      try {
        const parsedYear = Number.parseInt(year, 10)
        const result = await bopaApi.searchDocuments({
          q: debouncedSearch || undefined,
          organisme: organisme === ALL ? undefined : organisme,
          tema: tema === ALL ? undefined : tema,
          organisme_pare: organismePare === ALL ? undefined : organismePare,
          tema_pare: temaPare === ALL ? undefined : temaPare,
          year: Number.isNaN(parsedYear) ? undefined : parsedYear,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        })
        if (!active) return
        if (result.success && result.data) {
          setDocuments(result.data.items)
          setTotal(result.data.total)
        } else {
          setDocuments([])
          setTotal(0)
        }
      } catch (error) {
        console.error("[Strategos] Load BOPA documents error:", error)
        if (active) {
          setDocuments([])
          setTotal(0)
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    loadDocuments()
    return () => {
      active = false
    }
  }, [debouncedSearch, organisme, tema, organismePare, temaPare, year, dateFrom, dateTo, page])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const rangeStart = total === 0 ? 0 : page * PAGE_SIZE + 1
  const rangeEnd = Math.min(total, (page + 1) * PAGE_SIZE)

  const facetSelects = useMemo(
    () => [
      { label: "Organismo", value: organisme, onChange: setOrganisme, options: filterOptions.organisme },
      { label: "Tema", value: tema, onChange: setTema, options: filterOptions.tema },
      {
        label: "Organismo padre",
        value: organismePare,
        onChange: setOrganismePare,
        options: filterOptions.organisme_pare,
      },
      {
        label: "Tema padre",
        value: temaPare,
        onChange: setTemaPare,
        options: filterOptions.tema_pare,
      },
    ],
    [organisme, tema, organismePare, temaPare, filterOptions],
  )

  return (
    <div className="px-8 py-8">
      <h1 className="text-2xl font-bold text-slate-900">BOPA</h1>
      <p className="mt-1 text-sm text-slate-500">
        Consulta y filtra los documentos publicados en el Butlletí Oficial.
      </p>

      <div className="mt-6 flex flex-col gap-4">
        <Input
          type="search"
          placeholder="Buscar por título..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="h-11 bg-white sm:max-w-md"
        />

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {facetSelects.map((facet) => (
            <div key={facet.label} className="flex flex-col gap-1.5">
              <Label className="text-xs font-medium text-slate-500">{facet.label}</Label>
              <Select value={facet.value} onValueChange={facet.onChange}>
                <SelectTrigger className="h-11 bg-white">
                  <SelectValue placeholder="Todos" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Todos</SelectItem>
                  {facet.options.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:max-w-2xl">
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs font-medium text-slate-500">Año</Label>
            <Input
              type="number"
              inputMode="numeric"
              placeholder="p. ej. 2026"
              value={year}
              onChange={(event) => setYear(event.target.value)}
              className="h-11 bg-white"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs font-medium text-slate-500">Desde</Label>
            <Input
              type="date"
              value={dateFrom}
              onChange={(event) => setDateFrom(event.target.value)}
              className="h-11 bg-white"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label className="text-xs font-medium text-slate-500">Hasta</Label>
            <Input
              type="date"
              value={dateTo}
              onChange={(event) => setDateTo(event.target.value)}
              className="h-11 bg-white"
            />
          </div>
        </div>
      </div>

      <div className="mt-6">
        <BopaTable documents={documents} loading={loading} />
      </div>

      <div className="mt-4 flex flex-col items-center justify-between gap-3 sm:flex-row">
        <p className="text-sm text-slate-500">
          {total === 0
            ? "0 documentos"
            : `Mostrando ${rangeStart}–${rangeEnd} de ${total} documentos`}
        </p>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            onClick={() => setPage((prev) => Math.max(0, prev - 1))}
            disabled={loading || page === 0}
          >
            Anterior
          </Button>
          <span className="text-sm text-slate-500">
            Página {page + 1} de {totalPages}
          </span>
          <Button
            variant="outline"
            onClick={() => setPage((prev) => prev + 1)}
            disabled={loading || page + 1 >= totalPages}
          >
            Siguiente
          </Button>
        </div>
      </div>
    </div>
  )
}
