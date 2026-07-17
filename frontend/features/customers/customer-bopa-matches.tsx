"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { customersApi } from "@/features/customers/api"
import type { BopaDocument } from "@/features/bopa/api"
import { cn } from "@/lib/utils"
import { Search, Loader2 } from "lucide-react"

const HEAD_CLASS = "text-xs font-semibold uppercase tracking-wide text-slate-500"
const PAGE_SIZE = 10

export function CustomerBopaMatches({ customerId }: { customerId: string }) {
  const [documents, setDocuments] = useState<BopaDocument[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [offset, setOffset] = useState(0)
  const [hasSearched, setHasSearched] = useState(false)

  const triggerSearch = () => {
    setHasSearched(true)
  }

  useEffect(() => {
    if (!hasSearched) return

    let active = true

    const loadMatches = async () => {
      setLoading(true)
      try {
        const result = await customersApi.getCustomerBopaMatches(customerId, {
          limit: PAGE_SIZE,
          offset,
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
        console.error("[Strategos] Load customer BOPA matches error:", error)
        if (active) {
          setDocuments([])
          setTotal(0)
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    loadMatches()

    return () => {
      active = false
    }
  }, [customerId, offset, hasSearched])

  const pageCount = Math.ceil(total / PAGE_SIZE)
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1

  const handlePrevious = () => {
    setOffset(Math.max(0, offset - PAGE_SIZE))
  }

  const handleNext = () => {
    if (offset + PAGE_SIZE < total) {
      setOffset(offset + PAGE_SIZE)
    }
  }

  return (
    <section className="mt-8 w-full">
      <div className="pb-2">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Documentos BOPA Coincidentes</h2>
          <p className="mt-1 text-sm text-slate-500">
            Documentos del Boletín Oficial coincidentes con el cliente o sus proyectos.
          </p>
        </div>
      </div>

      <div className="mt-4 rounded-lg border border-slate-200 bg-white w-full">

        {!hasSearched ? (
          <div className="px-6 py-12 text-center text-sm text-slate-500">
            <Search className="mx-auto h-8 w-8 text-slate-400 stroke-[1.5]" />
            <p className="mt-2 text-sm font-medium text-slate-900">
              Búsqueda bajo demanda
            </p>
            <p className="mt-1 text-xs text-slate-500 max-w-sm mx-auto">
              Haz clic en el botón para escanear de forma segura el BOPA
              en busca de este cliente.
            </p>
            <Button
              onClick={triggerSearch}
              className="mt-4 border-slate-300 text-slate-700 hover:bg-slate-50"
            >
              Iniciar Escaneo
            </Button>
          </div>
        ) : loading ? (
          /*Loading state */
          <div className="px-6 py-12 text-center text-sm text-slate-500 flex flex-col items-center justify-center gap-2">
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
            <span>Consultando registros en el boletín...</span>
          </div>
        ) : documents.length === 0 ? (
          <div className="px-6 py-12 text-center text-sm text-slate-500">
            No se han encontrado documentos BOPA coincidentes.
          </div>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Documento</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Boletín</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Organismo</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Fecha</TableHead>
                  <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Acciones</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc) => (
                  <TableRow key={doc.id} className="border-slate-100">
                    <TableCell className="px-6 py-4 text-sm text-slate-900">
                      <div className="max-w-xs truncate font-medium">{doc.title}</div>
                      <div className="text-xs text-slate-500">{doc.document_name}</div>
                    </TableCell>
                    <TableCell className="px-6 py-4 text-sm text-slate-700">
                      <Link
                        href={`/bopa/${doc.bulletin_year}/${doc.bulletin_num}`}
                        className="font-medium hover:underline"
                      >
                        {doc.bulletin_year} núm. {doc.bulletin_num}
                      </Link>
                    </TableCell>
                    <TableCell className="px-6 py-4 text-sm text-slate-700">
                      {doc.organisme || "—"}
                    </TableCell>
                    <TableCell className="px-6 py-4 text-sm text-slate-500">
                      {new Date(doc.article_date).toLocaleDateString("es-ES")}
                    </TableCell>
                    <TableCell className="px-6 py-4 text-sm">
                      <Link
                        href={`/bopa/documents/${doc.id}`}
                        className="text-blue-600 hover:underline"
                      >
                        Ver
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            {pageCount > 1 && (
              <div className="flex items-center justify-between border-t border-slate-200 px-6 py-4">
                <p className="text-sm text-slate-500">
                  Página {currentPage} de {pageCount} ({total} documentos)
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handlePrevious}
                    disabled={offset === 0}
                  >
                    Anterior
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleNext}
                    disabled={offset + PAGE_SIZE >= total}
                  >
                    Siguiente
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  )
}
