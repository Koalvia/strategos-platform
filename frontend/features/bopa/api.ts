// BOPA feature API client (client-side).
// Calls the Next.js route handlers under /api/bopa — never the backend directly.

// A single BOPA document as returned by the backend search endpoint. Fields
// mirror the backend `DocumentSummary` schema (snake_case), which keeps the
// mapping to `BOPA núm. {bulletin_num}/{bulletin_year}` obvious.
export interface BopaDocument {
  id: number
  document_name: string
  title: string
  organisme: string
  tema: string
  article_date: string
  file_type: string
  source_url: string
  pdf_url: string
  bulletin_year: number
  bulletin_num: number
}

export interface BopaDocumentPage {
  items: BopaDocument[]
  total: number
}

export interface BopaFilterOptions {
  organisme: string[]
  tema: string[]
  organisme_pare: string[]
  tema_pare: string[]
}

export interface SearchDocumentsParams {
  q?: string
  organisme?: string
  tema?: string
  organisme_pare?: string
  tema_pare?: string
  year?: number
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}

export const bopaApi = {
  async searchDocuments(
    params: SearchDocumentsParams = {},
  ): Promise<{ success: boolean; data?: BopaDocumentPage; message?: string }> {
    const query = new URLSearchParams()
    if (params.q) query.set("q", params.q)
    if (params.organisme) query.set("organisme", params.organisme)
    if (params.tema) query.set("tema", params.tema)
    if (params.organisme_pare) query.set("organisme_pare", params.organisme_pare)
    if (params.tema_pare) query.set("tema_pare", params.tema_pare)
    if (params.year !== undefined) query.set("year", String(params.year))
    if (params.date_from) query.set("date_from", params.date_from)
    if (params.date_to) query.set("date_to", params.date_to)
    if (params.limit !== undefined) query.set("limit", String(params.limit))
    if (params.offset !== undefined) query.set("offset", String(params.offset))
    const queryString = query.toString()

    const response = await fetch(`/api/bopa/documents${queryString ? `?${queryString}` : ""}`)
    return response.json()
  },

  async getFilterOptions(): Promise<{
    success: boolean
    data?: BopaFilterOptions
    message?: string
  }> {
    const response = await fetch("/api/bopa/documents/filters")
    return response.json()
  },
}
