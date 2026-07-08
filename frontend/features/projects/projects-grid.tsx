import { ProjectCard } from "@/features/projects/project-card"
import type { Project, ProjectObligation } from "@/lib/types"

interface ProjectsGridProps {
  projects: Project[]
  // Soonest unfiled obligation per project id, used for the "Próx: …" line.
  nextObligations: Record<string, ProjectObligation>
  loading: boolean
}

export function ProjectsGrid({ projects, nextObligations, loading }: ProjectsGridProps) {
  if (loading) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500">
        Cargando proyectos...
      </div>
    )
  }

  if (projects.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500">
        No se han encontrado proyectos.
      </div>
    )
  }

  return (
    <div className="grid gap-5 md:grid-cols-2">
      {projects.map((project) => (
        <ProjectCard
          key={project.id}
          project={project}
          nextObligation={nextObligations[project.id]}
        />
      ))}
    </div>
  )
}
