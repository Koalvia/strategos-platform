interface ComingSoonProps {
  title: string
}

// Placeholder content rendered inside the app shell until the
// dedicated page task (#12–#17) fills it in.
export function ComingSoon({ title }: ComingSoonProps) {
  return (
    <div className="px-8 py-8">
      <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
      <div className="mt-8 flex min-h-[240px] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white">
        <p className="text-sm text-slate-500">Contenido próximamente</p>
      </div>
    </div>
  )
}
