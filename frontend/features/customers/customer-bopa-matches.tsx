"use client"

import { useCallback, useEffect, useState } from "react"
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
import { bopaApi, type BopaDocument, type BopaDocumentPage } from "@/features/bopa/api"
import { cn } from "@/lib/utils"
import { Loader2, RefreshCw } from "lucide-react"

const HEAD_CLASS = "text-xs font-semibold uppercase tracking-wide text-slate-500"
const PAGE_SIZE = 10

export function CustomerBopaMatches({ customerId }: { customerId: string }) {
  const [documents, setDocuments] = useState<BopaDocument[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  // Initial/paginated read of the matches the worker has already produced.
  const [loading, setLoading] = useState(true)
  // A user-triggered re-scan (runs the backend pipeline, then reloads).
  const [scanning, setScanning] = useState(false)
  // Set when a re-scan finished without surfacing any new match, so we can keep
  // the existing results on screen and add a small "nothing new" note.
  const [noNewMatches, setNoNewMatches] = useState(false)

  const fetchPage = useCallback(
    async (targetOffset: number): Promise<BopaDocumentPage> => {
      const result = await customersApi.getCustomerBopaMatches(customerId, {
        limit: PAGE_SIZE,
        offset: targetOffset,
      })
      if (result.success && result.data) return result.data
      return { items: [], total: 0 }
    },
    [customerId],
  )

  // Auto-load the matches on mount and whenever the page changes — the worker
  // has already populated them when it started, so there is no "search first"
  // gate anymore.
  useEffect(() => {
    let active = true

    setLoading(true)
    fetchPage(offset)
      .then((page) => {
        if (!active) return
        setDocuments(page.items)
        setTotal(page.total)
      })
      .catch((error) => {
        console.error("[Strategos] Load customer BOPA matches error:", error)
        if (!active) return
        setDocuments([])
        setTotal(0)
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [fetchPage, offset])

  // Re-run the BOPA scan on the backend, then reload from the first page. If the
  // total match count did not grow, tell the user there were no new bulletins
  // but keep the matches already on screen.
  const handleRescan = async () => {
    setScanning(true)
    setNoNewMatches(false)
    const previousTotal = total
    try {
      await bopaApi.runScan()
      const page = await fetchPage(0)
      setOffset(0)
      setDocuments(page.items)
      setTotal(page.total)
      if (page.total <= previousTotal) setNoNewMatches(true)
    } catch (error) {
      console.error("[Strategos] BOPA re-scan error:", error)
    } finally {
      setScanning(false)
    }
  }

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
      <div className="flex items-start justify-between gap-4 pb-2">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Documentos BOPA Coincidentes</h2>
          <p className="mt-1 text-sm text-slate-500">
            Documentos del Boletín Oficial coincidentes con el cliente o sus proyectos.
          </p>
        </div>
        <Button
          onClick={handleRescan}
          disabled={scanning}
          className="shrink-0 border-slate-300 text-slate-700 hover:bg-slate-50"
        >
          {scanning ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Escaneando...
            </>
          ) : (
            <>
              <RefreshCw className="h-4 w-4" />
              Iniciar Escaneo
            </>
          )}
        </Button>
      </div>

      {noNewMatches && (
        <p className="mt-2 text-xs text-slate-500">
          No hay nuevos boletines que coincidan.
        </p>
      )}

      <div className="mt-4 rounded-lg border border-slate-200 bg-white w-full">
        {loading ? (
          /* Loading state */
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
                      <Link href="/bopa" className="font-medium hover:underline">
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
                        href={`/bopa/${doc.id}?fromCustomer=${customerId}`}
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
