import { Card } from "@/components/ui/card"
import { cn } from "@/lib/utils"

interface KpiTileProps {
  // Small label above the number (e.g. "Proyectos activos").
  title: string
  // The headline figure — a raw count, or a pre-formatted string (e.g. a euro
  // amount) for the financial tiles.
  value: number | string
  // Muted sublabel below the number (e.g. "de 12 totales").
  sublabel: string
  // Amber sublabel for the "Obligaciones próximas" tile in dashboard.png.
  accent?: boolean
  // "count" (default) shows a short integer at text-4xl. "money" shows a
  // pre-formatted currency string (e.g. "3.300,00 €") a size smaller so it does
  // not wrap or overflow on narrow screens.
  variant?: "count" | "money"
}

export function KpiTile({
  title,
  value,
  sublabel,
  accent = false,
  variant = "count",
}: KpiTileProps) {
  return (
    <Card className="gap-3 border-slate-200 px-6 py-5">
      <p className="text-sm font-medium text-slate-500">{title}</p>
      <p
        className={cn(
          "font-bold text-slate-900",
          variant === "money" ? "text-3xl" : "text-4xl",
        )}
      >
        {value}
      </p>
      <p className={cn("text-sm", accent ? "text-amber-600" : "text-slate-500")}>
        {sublabel}
      </p>
    </Card>
  )
}
