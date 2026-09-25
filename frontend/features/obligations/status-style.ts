import type { ObligationStatus } from "@/lib/types"

// Shared traffic-light styles for obligation statuses, used by both the
// dashboard "Próximas obligaciones" widget and the Obligaciones table so the
// maps live in one place. Colours mirror the "Próximas obligaciones" widget in
// dashboard.png: overdue/urgent red, upcoming amber, on-track green, undated
// neutral. "Urgente" shares the red family with "Vencido" but keeps its label.

export const STATUS_BADGE: Record<ObligationStatus, string> = {
  Vencido: "bg-red-100 text-red-700",
  Urgente: "bg-red-100 text-red-700",
  Próximo: "bg-amber-100 text-amber-700",
  "Al día": "bg-green-100 text-green-700",
  "Sin fecha": "bg-slate-100 text-slate-500",
}

export const STATUS_DOT: Record<ObligationStatus, string> = {
  Vencido: "bg-red-500",
  Urgente: "bg-red-500",
  Próximo: "bg-amber-500",
  "Al día": "bg-green-500",
  "Sin fecha": "bg-slate-400",
}
