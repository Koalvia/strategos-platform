"use client"

import { useState } from "react"
import { ChevronRight } from "lucide-react"

import { Card } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"
import type { CustomerBillingGroup } from "@/lib/types"
import { formatEuro, formatHours } from "./format"

const HEAD_CLASS = "text-xs font-semibold uppercase tracking-wide text-slate-500"
// Right-aligned, tabular figures so decimals line up and widths don't jump.
const NUM_CLASS = "px-6 py-3 text-right tabular-nums"

interface FacturacionResumenProps {
  groups: CustomerBillingGroup[]
}

// Unified billing table: each customer is an expandable parent row carrying its
// authoritative net billing (and its projects' rolled-up cost/hours), and
// expanding it reveals that customer's projects with their own billing, usage
// cost and logged hours. Sourced live from Business Central. Replaces the
// separate per-customer and per-project tables for a more compact overview.
export function FacturacionResumen({ groups }: FacturacionResumenProps) {
  // Which customer rows are expanded. Collapsed by default to stay compact.
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (customerId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(customerId)) {
        next.delete(customerId)
      } else {
        next.add(customerId)
      }
      return next
    })
  }

  return (
    <Card className="gap-0 border-slate-200 py-0">
      <h2 className="border-b border-slate-100 px-6 py-5 text-lg font-bold text-slate-900">
        Facturación
      </h2>
      {groups.length === 0 ? (
        <p className="px-6 py-12 text-center text-sm text-slate-500">
          Sin facturación registrada.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>
                Cliente / Proyecto
              </TableHead>
              <TableHead className={cn(HEAD_CLASS, "px-6 py-4 text-right")}>
                Facturación
              </TableHead>
              <TableHead className={cn(HEAD_CLASS, "px-6 py-4 text-right")}>
                Coste
              </TableHead>
              <TableHead className={cn(HEAD_CLASS, "px-6 py-4 text-right")}>
                Horas
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {groups.map((group) => {
              const isOpen = expanded.has(group.customer_id)
              const hasProjects = group.projects.length > 0
              return (
                <FacturacionGroup
                  key={group.customer_id}
                  group={group}
                  isOpen={isOpen}
                  hasProjects={hasProjects}
                  onToggle={() => toggle(group.customer_id)}
                />
              )
            })}
          </TableBody>
        </Table>
      )}
    </Card>
  )
}

interface FacturacionGroupProps {
  group: CustomerBillingGroup
  isOpen: boolean
  hasProjects: boolean
  onToggle: () => void
}

function FacturacionGroup({
  group,
  isOpen,
  hasProjects,
  onToggle,
}: FacturacionGroupProps) {
  return (
    <>
      <TableRow className="border-slate-100">
        <TableCell className="px-6 py-4 font-medium text-slate-900">
          {/* The disclosure control is a real <button> (aria-expanded lives on
              it, not on the <tr>, whose implicit row role does not support it).
              Customers with no projects render a plain, non-interactive label. */}
          {hasProjects ? (
            <button
              type="button"
              aria-expanded={isOpen}
              onClick={onToggle}
              className="flex w-full items-center gap-2 text-left rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#caa53d]"
            >
              <ChevronRight
                className={cn(
                  "size-4 shrink-0 text-slate-400 transition-transform",
                  isOpen && "rotate-90",
                )}
              />
              <span className="max-w-xs truncate" title={group.customer_name}>
                {group.customer_name}
              </span>
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <span className="size-4 shrink-0" aria-hidden />
              <span className="max-w-xs truncate" title={group.customer_name}>
                {group.customer_name}
              </span>
            </div>
          )}
        </TableCell>
        <TableCell className={cn(NUM_CLASS, "py-4 font-medium text-slate-900")}>
          {formatEuro(group.net_billed)}
        </TableCell>
        <TableCell className={cn(NUM_CLASS, "py-4 text-slate-700")}>
          {formatEuro(group.cost)}
        </TableCell>
        <TableCell className={cn(NUM_CLASS, "py-4 text-slate-500")}>
          {formatHours(group.hours)}
        </TableCell>
      </TableRow>
      {isOpen &&
        group.projects.map((project) => (
          <TableRow
            key={project.project_id}
            className="border-slate-100 bg-slate-50/60 hover:bg-slate-50"
          >
            <TableCell className="py-3 pr-6 pl-14">
              {/* Truncate long names so they never squeeze the numeric columns;
                  title keeps the full name on hover and the id subline aids
                  quick identification. */}
              <div
                className="max-w-[16rem] truncate text-sm text-slate-700"
                title={project.project_name}
              >
                {project.project_name}
              </div>
              <div className="text-xs text-slate-400">{project.project_id}</div>
            </TableCell>
            <TableCell className={cn(NUM_CLASS, "text-slate-700")}>
              {formatEuro(project.billed)}
            </TableCell>
            <TableCell className={cn(NUM_CLASS, "text-slate-700")}>
              {formatEuro(project.cost)}
            </TableCell>
            <TableCell className={cn(NUM_CLASS, "text-slate-500")}>
              {formatHours(project.hours)}
            </TableCell>
          </TableRow>
        ))}
    </>
  )
}
