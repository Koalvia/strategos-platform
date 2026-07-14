"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { useParams } from "next/navigation"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { customersApi } from "@/features/customers/api"
import { projectsApi } from "@/features/projects/api"
import { cn } from "@/lib/utils"
import type { Customer, Project } from "@/lib/types"

const HEAD_CLASS = "text-xs font-semibold uppercase tracking-wide text-slate-500"

// A single label/value row in the customer fitxa grid.
function Field({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <span className="text-sm text-slate-900">{children}</span>
    </div>
  )
}

function StatusBadge({ status }: { status: Customer["status"] | Project["status"] }) {
  return (
    <Badge
      variant="secondary"
      className={cn(
        "font-medium",
        status === "Activo"
          ? "bg-green-100 text-green-700"
          : "bg-slate-100 text-slate-500",
      )}
    >
      {status}
    </Badge>
  )
}

export default function ClienteDetailPage() {
  const params = useParams<{ id: string }>()
  const id = params.id

  const [customer, setCustomer] = useState<Customer | null>(null)
  const [projects, setProjects] = useState<Project[]>([])
  const [loadingCustomer, setLoadingCustomer] = useState(true)
  const [loadingProjects, setLoadingProjects] = useState(true)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    if (!id) return
    let active = true

    const loadCustomer = async () => {
      setLoadingCustomer(true)
      setNotFound(false)
      try {
        const result = await customersApi.getCustomer(id)
        if (!active) return
        if (result.success && result.data) {
          setCustomer(result.data)
        } else {
          setCustomer(null)
          setNotFound(true)
        }
      } catch (error) {
        console.error("[Strategos] Load customer error:", error)
        if (active) {
          setCustomer(null)
          setNotFound(true)
        }
      } finally {
        if (active) setLoadingCustomer(false)
      }
    }

    const loadProjects = async () => {
      setLoadingProjects(true)
      try {
        const result = await projectsApi.getProjects({ customerId: id })
        if (!active) return
        setProjects(result.success && result.data ? result.data.items : [])
      } catch (error) {
        console.error("[Strategos] Load customer projects error:", error)
        if (active) setProjects([])
      } finally {
        if (active) setLoadingProjects(false)
      }
    }

    loadCustomer()
    loadProjects()

    return () => {
      active = false
    }
  }, [id])

  if (loadingCustomer) {
    return (
      <div className="px-8 py-8">
        <div className="rounded-lg border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500">
          Cargando cliente...
        </div>
      </div>
    )
  }

  if (notFound || !customer) {
    return (
      <div className="px-8 py-8">
        <div className="rounded-lg border border-slate-200 bg-white px-6 py-12 text-center">
          <p className="text-sm text-slate-500">No se ha encontrado el cliente.</p>
          <Link
            href="/clientes"
            className="mt-4 inline-block text-sm font-semibold text-slate-900 underline"
          >
            Volver a Clientes
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="px-8 py-8">
      <Link href="/clientes" className="text-sm text-slate-500 hover:text-slate-900">
        ← Clientes
      </Link>

      <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-slate-900">{customer.name}</h1>
          <p className="text-sm text-slate-500">{customer.nif}</p>
        </div>
        <StatusBadge status={customer.status} />
      </div>

      <Card className="mt-6 border-slate-200 px-6 py-6">
        <h2 className="text-lg font-bold text-slate-900">General</h2>
        <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Nombre">{customer.name}</Field>
          <Field label="NIF">{customer.nif}</Field>
          <Field label="Tipo de entidad">{customer.entityType || "—"}</Field>
          <Field label="Responsable">{customer.responsible}</Field>
          <Field label="Proyectos">{customer.projectCount}</Field>
          <Field label="Estado">{customer.status}</Field>
        </div>
      </Card>

      <section className="mt-8">
        <h2 className="text-lg font-bold text-slate-900">Proyectos</h2>
        <div className="mt-4 rounded-lg border border-slate-200 bg-white">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Proyecto</TableHead>
                <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Responsable</TableHead>
                <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Técnico</TableHead>
                <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Estado</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loadingProjects ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={4} className="px-6 py-12 text-center text-sm text-slate-500">
                    Cargando proyectos...
                  </TableCell>
                </TableRow>
              ) : projects.length === 0 ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={4} className="px-6 py-12 text-center text-sm text-slate-500">
                    No se han encontrado proyectos.
                  </TableCell>
                </TableRow>
              ) : (
                projects.map((project) => (
                  <TableRow key={project.id} className="border-slate-100">
                    <TableCell className="px-6 py-4 font-semibold text-slate-900">
                      <Link href={`/proyectos/${project.id}`} className="hover:underline">
                        {project.name}
                      </Link>
                    </TableCell>
                    <TableCell className="px-6 py-4 text-slate-700">
                      {project.responsible || "—"}
                    </TableCell>
                    <TableCell className="px-6 py-4 text-slate-700">
                      {project.technician || "—"}
                    </TableCell>
                    <TableCell className="px-6 py-4">
                      <StatusBadge status={project.status} />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </section>
    </div>
  )
}
