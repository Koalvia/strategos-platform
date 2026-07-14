"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import DOMPurify from "isomorphic-dompurify"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { bopaApi, type BopaDocumentDetail } from "@/features/bopa/api"

// Render `article_date` as a plain locale date; the backend sends an ISO
// datetime but only the day is meaningful here (mirrors the search table).
function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString("es-ES")
}

// A single label/value row in the metadata grid.
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

export default function BopaDocumentDetailPage() {
  const params = useParams<{ id: string }>()
  const id = params.id

  const [document, setDocument] = useState<BopaDocumentDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    if (!id) return
    let active = true

    const loadDocument = async () => {
      setLoading(true)
      setNotFound(false)
      try {
        const result = await bopaApi.getDocument(id)
        if (!active) return
        if (result.success && result.data) {
          setDocument(result.data)
        } else {
          setDocument(null)
          setNotFound(true)
        }
      } catch (error) {
        console.error("[Strategos] Load BOPA document error:", error)
        if (active) {
          setDocument(null)
          setNotFound(true)
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    loadDocument()
    return () => {
      active = false
    }
  }, [id])

  // `html_content` is upstream-sourced BOPA markup, not authored by this app, so
  // it MUST be sanitized before it ever reaches `dangerouslySetInnerHTML`.
  const htmlContent = document?.html_content ?? null
  const sanitizedHtml = useMemo(() => {
    if (!htmlContent) return null
    return DOMPurify.sanitize(htmlContent)
  }, [htmlContent])

  if (loading) {
    return (
      <div className="px-8 py-8">
        <div className="rounded-lg border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500">
          Cargando documento...
        </div>
      </div>
    )
  }

  if (notFound || !document) {
    return (
      <div className="px-8 py-8">
        <div className="rounded-lg border border-slate-200 bg-white px-6 py-12 text-center">
          <p className="text-sm text-slate-500">No se ha encontrado el documento.</p>
          <Link
            href="/bopa"
            className="mt-4 inline-block text-sm font-semibold text-slate-900 underline"
          >
            Volver a BOPA
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="px-8 py-8">
      <Link href="/bopa" className="text-sm text-slate-500 hover:text-slate-900">
        ← BOPA
      </Link>

      <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
        <h1 className="min-w-0 text-2xl font-bold text-slate-900">{document.title}</h1>
        {document.pdf_url ? (
          <Button asChild variant="outline" className="shrink-0">
            <a href={document.pdf_url} target="_blank" rel="noopener noreferrer">
              Ver PDF original
            </a>
          </Button>
        ) : null}
      </div>

      <Card className="mt-6 border-slate-200 px-6 py-6">
        <h2 className="text-lg font-bold text-slate-900">Detalles</h2>
        <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Organismo">{document.organisme || "—"}</Field>
          <Field label="Tema">{document.tema || "—"}</Field>
          <Field label="Fecha">{formatDate(document.article_date)}</Field>
          <Field label="Tipo de archivo">{document.file_type || "—"}</Field>
          <Field label="Boletín">
            BOPA núm. {document.bulletin_num}/{document.bulletin_year}
          </Field>
        </div>
      </Card>

      <Card className="mt-6 border-slate-200 px-6 py-6">
        <h2 className="text-lg font-bold text-slate-900">Contenido</h2>
        {sanitizedHtml ? (
          <div
            className="prose prose-slate mt-4 max-w-none text-sm text-slate-900"
            // Sanitized above with DOMPurify — never render raw upstream HTML.
            dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
          />
        ) : (
          <p className="mt-4 text-sm text-slate-500">
            Este documento no tiene contenido HTML disponible. Consulta el PDF original.
          </p>
        )}
      </Card>
    </div>
  )
}
