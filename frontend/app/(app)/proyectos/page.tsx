"use client"

import { useEffect, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { projectsApi } from "@/features/projects/api"
import { ProjectsGrid } from "@/features/projects/projects-grid"
import type { Project, ProjectObligation } from "@/lib/types"

const ALL = "all"

// Reduce the obligation list to the soonest unfiled instance per project. The
// backend returns instances ordered by due date ascending, so the first unfiled
// one seen for a project is its next obligation.
function buildNextObligations(
  obligations: ProjectObligation[],
): Record<string, ProjectObligation> {
  const next: Record<string, ProjectObligation> = {}
  for (const obligation of obligations) {
    if (obligation.submissionDate) continue
    if (!next[obligation.project.id]) {
      next[obligation.project.id] = obligation
    }
  }
  return next
}

export default function ProyectosPage() {
  const [search, setSearch] = useState("")
  const [projectType, setProjectType] = useState(ALL)
  const [entityType, setEntityType] = useState(ALL)
  const [projects, setProjects] = useState<Project[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [nextObligations, setNextObligations] = useState<
    Record<string, ProjectObligation>
  >({})
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)

  // Filter dropdown options are derived from whatever projects have loaded so
  // far rather than a separate full fetch: project_type/entity_type have no
  // live BC source yet (see BCProject), so live mode's options are always
  // empty regardless of how much is scanned, and the mock fixture set
  // comfortably fits within one page, so this stays exhaustive there too.
  const projectTypeOptions = useMemo(
    () =>
      Array.from(
        new Set(projects.map((p) => p.projectType).filter((v): v is string => !!v)),
      ).sort(),
    [projects],
  )
  const entityTypeOptions = useMemo(
    () =>
      Array.from(
        new Set(projects.map((p) => p.entityType).filter((v): v is string => !!v)),
      ).sort(),
    [projects],
  )

  // Debounce the search term so typing doesn't hit the backend on every keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState("")
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(handle)
  }, [search])

  // Load the obligations once (used for each card's "Próx: ..." line).
  useEffect(() => {
    let active = true

    const loadObligations = async () => {
      try {
        const result = await projectsApi.getObligations()
        if (!active) return
        setNextObligations(
          result.success && result.data ? buildNextObligations(result.data) : {},
        )
      } catch (error) {
        console.error("[Strategos] Load obligations error:", error)
      }
    }

    loadObligations()
    return () => {
      active = false
    }
  }, [])

  // Whenever the search/filter dropdowns change, restart pagination from page 1.
  useEffect(() => {
    let active = true

    const loadProjects = async () => {
      setLoading(true)
      try {
        const result = await projectsApi.getProjects({
          search: debouncedSearch || undefined,
          projectType: projectType === ALL ? undefined : projectType,
          entityType: entityType === ALL ? undefined : entityType,
        })
        if (!active) return
        if (result.success && result.data) {
          setProjects(result.data.items)
          setNextCursor(result.data.nextCursor)
        } else {
          setProjects([])
          setNextCursor(null)
        }
      } catch (error) {
        console.error("[Strategos] Load projects error:", error)
        if (active) {
          setProjects([])
          setNextCursor(null)
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    loadProjects()
    return () => {
      active = false
    }
  }, [debouncedSearch, projectType, entityType])

  const handleLoadMore = async () => {
    if (!nextCursor) return
    setLoadingMore(true)
    try {
      const result = await projectsApi.getProjects({
        search: debouncedSearch || undefined,
        projectType: projectType === ALL ? undefined : projectType,
        entityType: entityType === ALL ? undefined : entityType,
        cursor: nextCursor,
      })
      if (result.success && result.data) {
        setProjects((prev) => [...prev, ...result.data!.items])
        setNextCursor(result.data.nextCursor)
      }
    } catch (error) {
      console.error("[Strategos] Load more projects error:", error)
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <div className="px-8 py-8">
      <h1 className="text-2xl font-bold text-slate-900">Proyectos</h1>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <Input
          type="search"
          placeholder="Buscar proyecto..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="h-11 bg-white sm:max-w-md"
        />
        <Select value={projectType} onValueChange={setProjectType}>
          <SelectTrigger className="h-11 bg-white sm:w-48">
            <SelectValue placeholder="Todos" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos</SelectItem>
            {projectTypeOptions.map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={entityType} onValueChange={setEntityType}>
          <SelectTrigger className="h-11 bg-white sm:w-48">
            <SelectValue placeholder="Todos" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos</SelectItem>
            {entityTypeOptions.map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="mt-6">
        <ProjectsGrid
          projects={projects}
          nextObligations={nextObligations}
          loading={loading}
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
