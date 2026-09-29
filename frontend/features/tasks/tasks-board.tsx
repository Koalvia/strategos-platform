"use client"

import { useDraggable, useDroppable } from "@dnd-kit/core"
import { CSS } from "@dnd-kit/utilities"

import { cn } from "@/lib/utils"
import { TaskCard } from "./task-card"
import { TASK_STATUS_ORDER, TASK_STATUS_SHORT_LABEL } from "./status"
import type { Task, TaskStatus } from "@/lib/types"

interface TasksBoardProps {
  tasks: Task[]
  loading: boolean
}

// A task card that can be dragged to another column. Kept as a thin wrapper so
// TaskCard stays presentational.
function DraggableTaskCard({ task }: { task: Task }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: task.id,
  })
  const style = {
    transform: CSS.Translate.toString(transform),
    opacity: isDragging ? 0.5 : undefined,
  }
  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className="cursor-grab touch-none active:cursor-grabbing"
    >
      <TaskCard task={task} />
    </div>
  )
}

// A board column that accepts dropped cards. Its droppable id is the status, which
// the page's onDragEnd reads to know the target column.
function DroppableColumn({ status, tasks }: { status: TaskStatus; tasks: Task[] }) {
  const { setNodeRef, isOver } = useDroppable({ id: status })
  return (
    <section
      ref={setNodeRef}
      className={cn(
        "rounded-lg bg-slate-100/60 p-4 transition-shadow",
        isOver && "ring-2 ring-[#caa53d]",
      )}
    >
      <h2
        className="mb-4 truncate px-1 text-sm font-semibold text-slate-500"
        title={status}
      >
        {TASK_STATUS_SHORT_LABEL[status]} · {tasks.length}
      </h2>
      <div className="space-y-4">
        {tasks.length === 0 ? (
          <p className="px-1 text-sm text-slate-400">Sin tareas.</p>
        ) : (
          tasks.map((task) => <DraggableTaskCard key={task.id} task={task} />)
        )}
      </div>
    </section>
  )
}

export function TasksBoard({ tasks, loading }: TasksBoardProps) {
  if (loading) {
    return (
      <div className="flex min-h-60 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white">
        <p className="text-sm text-slate-500">Cargando tareas...</p>
      </div>
    )
  }

  // Group tasks into their board column, preserving backend order within each.
  const byStatus = Object.fromEntries(
    TASK_STATUS_ORDER.map((status) => [status, [] as Task[]]),
  ) as Record<TaskStatus, Task[]>
  for (const task of tasks) {
    byStatus[task.status]?.push(task)
  }

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
      {TASK_STATUS_ORDER.map((status) => (
        <DroppableColumn key={status} status={status} tasks={byStatus[status]} />
      ))}
    </div>
  )
}
