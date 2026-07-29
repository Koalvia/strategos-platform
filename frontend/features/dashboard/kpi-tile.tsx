import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
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
  // True while this tile's own figure is in flight. Each KPI has its own
  // endpoint, so tiles resolve at different times — a pending one shimmers
  // instead of showing "—", which would read as a real "unavailable".
  isLoading?: boolean
}

export function KpiTile({
  title,
  value,
  sublabel,
  accent = false,
  variant = "count",
  isLoading = false,
}: KpiTileProps) {
  return (
    <Card className="gap-3 border-slate-200 px-6 py-5">
      {/* The title is static copy, not data, so it renders even while loading. */}
      <p className="text-sm font-medium text-slate-500">{title}</p>
      {isLoading ? (
        // Placeholder heights match the real lines below, so the tile keeps its
        // final size and the grid does not reflow when the figure lands.
        <>
          <Skeleton className={variant === "money" ? "h-9 w-28" : "h-10 w-20"} />
          <Skeleton className="h-5 w-28" />
        </>
      ) : (
        <>
          <p
            className={cn(
              "font-bold text-slate-900",
              variant === "money" ? "text-3xl" : "text-4xl",
            )}
          >
            {value}
          </p>
          <p
            className={cn(
              "text-sm",
              accent ? "text-amber-600" : "text-slate-500",
            )}
          >
            {sublabel}
          </p>
        </>
      )}
    </Card>
  )
}
