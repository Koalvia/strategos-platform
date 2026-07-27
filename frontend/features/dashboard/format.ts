// Shared formatters for the dashboard's financial widgets. Amounts are in local
// currency (EUR); hours are plain quantities. Spanish locale so thousands use a
// dot and decimals a comma ("3.300,00 €").

const EUR = new Intl.NumberFormat("es-ES", {
  style: "currency",
  currency: "EUR",
})

const HOURS = new Intl.NumberFormat("es-ES", {
  maximumFractionDigits: 1,
})

// An em dash stands in for a figure Business Central could not serve, so an
// unavailable column reads as "unknown" rather than as a real zero (and never as
// the "NaN €" Intl would produce for a nullish input).
export const UNAVAILABLE = "—"

export function formatEuro(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return UNAVAILABLE
  return EUR.format(amount)
}

export function formatHours(quantity: number | null | undefined): string {
  if (quantity === null || quantity === undefined) return UNAVAILABLE
  return `${HOURS.format(quantity)} h`
}
