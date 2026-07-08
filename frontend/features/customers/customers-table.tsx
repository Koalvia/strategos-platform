import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"
import type { Customer } from "@/lib/types"

interface CustomersTableProps {
  customers: Customer[]
  loading: boolean
}

const HEAD_CLASS =
  "text-xs font-semibold uppercase tracking-wide text-slate-500"

export function CustomersTable({ customers, loading }: CustomersTableProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Cliente</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>NIF</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Tipo</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Responsable</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Proyectos</TableHead>
            <TableHead className={cn(HEAD_CLASS, "px-6 py-4")}>Estado</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {loading ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={6} className="px-6 py-12 text-center text-sm text-slate-500">
                Cargando clientes...
              </TableCell>
            </TableRow>
          ) : customers.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={6} className="px-6 py-12 text-center text-sm text-slate-500">
                No se han encontrado clientes.
              </TableCell>
            </TableRow>
          ) : (
            customers.map((customer) => (
              <TableRow key={customer.nif} className="border-slate-100">
                <TableCell className="px-6 py-4 font-semibold text-slate-900">
                  {customer.name}
                </TableCell>
                <TableCell className="px-6 py-4 text-slate-500">{customer.nif}</TableCell>
                <TableCell className="px-6 py-4">
                  <Badge
                    variant="secondary"
                    className="bg-slate-100 font-medium text-slate-600"
                  >
                    {customer.entityType}
                  </Badge>
                </TableCell>
                <TableCell className="px-6 py-4 text-slate-700">
                  {customer.responsible}
                </TableCell>
                <TableCell className="px-6 py-4 text-slate-700">
                  {customer.projectCount}
                </TableCell>
                <TableCell className="px-6 py-4">
                  <Badge
                    variant="secondary"
                    className={cn(
                      "font-medium",
                      customer.status === "Activo"
                        ? "bg-green-100 text-green-700"
                        : "bg-slate-100 text-slate-500",
                    )}
                  >
                    {customer.status}
                  </Badge>
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}
