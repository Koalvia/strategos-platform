// Single source of truth for the Tareas board columns: their display order and a
// short header label. The status *value* stays the full BC/platform string (used
// as the board column key, the API filter, and the PATCH payload); only the column
// header is shortened because "Esperando información / respuesta del cliente" is
// too long to sit above a narrow column.
import type { TaskStatus } from "@/lib/types"

export const TASK_STATUS_ORDER: TaskStatus[] = [
  "Pendiente",
  "En curso",
  "Esperando información / respuesta del cliente",
  "Hecho",
]

export const TASK_STATUS_SHORT_LABEL: Record<TaskStatus, string> = {
  "Pendiente": "Pendiente",
  "En curso": "En curso",
  "Esperando información / respuesta del cliente": "Esperando cliente",
  "Hecho": "Hecho",
}
