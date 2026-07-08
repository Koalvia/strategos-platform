"use client"

import { useEffect, useMemo, useState } from "react"

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
  const [nextObligations, setNextObligations] = useState<
    Record<string, ProjectObligation>
  >({})
  const [loading, setLoading] = useState(true)

  // Filter dropdown options come from a one-time unfiltered fetch so narrowing
  // the grid never shrinks the option lists.
  const [allProjects, setAllProjects] = useState<Project[]>([])

  const projectTypeOptions = useMemo(
    () => Array.from(new Set(allProjects.map((p) => p.projectType))).sort(),
    [allProjects],
  )
  const entityTypeOptions = useMemo(
    () => Array.from(new Set(allProjects.map((p) => p.entityType))).sort(),
    [allProjects],
  )

  // Debounce the search term so typing doesn't hit the backend on every keystroke.
  const [debouncedSearch, setDebouncedSearch] = useState("")
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(handle)
  }, [search])

  // Load the obligations once and the full project list for the filter options.
  useEffect(() => {
    let active = true

    const loadOnce = async () => {
      try {
        const [obligationsResult, projectsResult] = await Promise.all([
          projectsApi.getObligations(),
          projectsApi.getProjects(),
        ])
        if (!active) return
        setNextObligations(
          obligationsResult.success && obligationsResult.data
            ? buildNextObligations(obligationsResult.data)
            : {},
        )
        setAllProjects(
          projectsResult.success && projectsResult.data ? projectsResult.data : [],
        )
      } catch (error) {
        console.error("[Strategos] Load projects metadata error:", error)
      }
    }

    loadOnce()
    return () => {
      active = false
    }
  }, [])

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
        setProjects(result.success && result.data ? result.data : [])
      } catch (error) {
        console.error("[Strategos] Load projects error:", error)
        if (active) setProjects([])
      } finally {
        if (active) setLoading(false)
      }
    }

    loadProjects()
    return () => {
      active = false
    }
  }, [debouncedSearch, projectType, entityType])

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
    </div>
  )
}
