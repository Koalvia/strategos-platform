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

export function formatEuro(amount: number): string {
  return EUR.format(amount)
}

export function formatHours(quantity: number): string {
  return `${HOURS.format(quantity)} h`
}
