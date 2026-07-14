"use client"

import { useRouter } from "next/navigation"

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"
import type { BopaDocument } from "@/features/bopa/api"

interface BopaTableProps {
  documents: BopaDocument[]
  loading: boolean
}

const HEAD_CLASS = "text-xs font-semibold uppercase tracking-wide text-slate-500"

// Render `article_date` as a plain locale date; the backend sends an ISO
// datetime but only the day is meaningful here.
function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString("es-ES")
}

export function BopaTable({ documents, loading }: BopaTableProps) {
  const router = useRouter()

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Título</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Organismo</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Tema</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Fecha</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Boletín</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={5} className="px-6 py-12 text-center text-sm text-slate-500">
                Cargando documentos...
              </TableCell>
            </TableRow>
          ) : documents.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={5} className="px-6 py-12 text-center text-sm text-slate-500">
                No se han encontrado documentos.
              </TableCell>
            </TableRow>
          ) : (
            documents.map((document) => {
              const href = `/bopa/${document.id}`
              return (
                <TableRow
                  key={document.id}
                  role="link"
                  tabIndex={0}
                  onClick={() => router.push(href)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault()
                      router.push(href)
                    }
                  }}
                  className="cursor-pointer border-slate-100 hover:bg-slate-50"
                >
                  <TableCell className="max-w-md px-6 py-4 font-semibold text-slate-900">
                    {document.title}
                  </TableCell>
                  <TableCell className="px-6 py-4 text-slate-700">{document.organisme}</TableCell>
                  <TableCell className="px-6 py-4 text-slate-700">{document.tema}</TableCell>
                  <TableCell className="px-6 py-4 whitespace-nowrap text-slate-500">
                    {formatDate(document.article_date)}
                  </TableCell>
                  <TableCell className="px-6 py-4 whitespace-nowrap text-slate-500">
                    BOPA núm. {document.bulletin_num}/{document.bulletin_year}
                  </TableCell>
                </TableRow>
              )
            })
          )}
        </TableBody>
      </Table>
    </div>
  )
}
