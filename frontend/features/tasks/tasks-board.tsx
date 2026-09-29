"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  closestCorners,
  getFirstCollision,
  pointerWithin,
  rectIntersection,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core"
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { toast } from "sonner"

import { cn } from "@/lib/utils"
import { tasksApi } from "@/features/tasks/api"
import { TaskCard } from "./task-card"
import { TASK_STATUS_ORDER, TASK_STATUS_SHORT_LABEL } from "./status"
import type { Task, TaskStatus } from "@/lib/types"

interface TasksBoardProps {
  tasks: Task[]
  loading: boolean
}

type Columns = Record<TaskStatus, Task[]>

// Group a flat task list into its board columns, preserving order within each.
function groupByColumn(tasks: Task[]): Columns {
  const columns = Object.fromEntries(
    TASK_STATUS_ORDER.map((status) => [status, [] as Task[]]),
  ) as Columns
  for (const task of tasks) columns[task.status]?.push(task)
  return columns
}

// A sortable card: draggable up/down within a column and across columns.
function SortableCard({ task }: { task: Task }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: task.id })
  const style = {
    transform: CSS.Translate.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : undefined,
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

// A droppable column hosting a vertical SortableContext of its cards.
function Column({ status, tasks }: { status: TaskStatus; tasks: Task[] }) {
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
      <SortableContext
        items={tasks.map((t) => t.id)}
        strategy={verticalListSortingStrategy}
      >
        <div className="min-h-16 space-y-4">
          {tasks.length === 0 ? (
            <p className="px-1 text-sm text-slate-400">Sin tareas.</p>
          ) : (
            tasks.map((task) => <SortableCard key={task.id} task={task} />)
          )}
        </div>
      </SortableContext>
    </section>
  )
}

export function TasksBoard({ tasks, loading }: TasksBoardProps) {
  const [columns, setColumns] = useState<Columns>(() => groupByColumn(tasks))
  const [activeId, setActiveId] = useState<string | null>(null)
  // Snapshot taken at drag start, for rollback if persisting the move fails.
  const [beforeDrag, setBeforeDrag] = useState<Columns | null>(null)

  // Resync when the fetched tasks change (filter change, reload). A successful
  // drag does not refetch, so this never clobbers an optimistic reorder.
  useEffect(() => {
    setColumns(groupByColumn(tasks))
  }, [tasks])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  )

  const activeTask = useMemo(
    () =>
      activeId
        ? Object.values(columns).flat().find((t) => t.id === activeId) ?? null
        : null,
    [activeId, columns],
  )

  // The column a card id lives in; an ``over`` id may itself be an (empty) column.
  const columnOf = (id: string): TaskStatus | null => {
    if (TASK_STATUS_ORDER.includes(id as TaskStatus)) return id as TaskStatus
    return (
      (Object.keys(columns) as TaskStatus[]).find((s) =>
        columns[s].some((t) => t.id === id),
      ) ?? null
    )
  }

  // Pointer-first collision so empty/short columns are droppable; when the pointer
  // lands on a column that has cards, retarget to the closest card so sorting works.
  const collisionDetection: CollisionDetection = useCallback(
    (args) => {
      const hits = pointerWithin(args)
      const base = hits.length > 0 ? hits : rectIntersection(args)
      const overId = getFirstCollision(base, "id")
      if (overId == null) return base
      if (TASK_STATUS_ORDER.includes(overId as TaskStatus)) {
        const cardIds = columns[overId as TaskStatus].map((t) => t.id)
        if (cardIds.length > 0) {
          const closest = closestCorners({
            ...args,
            droppableContainers: args.droppableContainers.filter(
              (c) => c.id !== overId && cardIds.includes(String(c.id)),
            ),
          })
          if (closest.length > 0) return closest
        }
      }
      return [{ id: overId }]
    },
    [columns],
  )

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(String(event.active.id))
    setBeforeDrag(columns)
  }

  // Move the dragged card into the column it is hovering, so it renders there live.
  const handleDragOver = (event: DragOverEvent) => {
    const { active, over } = event
    if (!over) return
    const from = columnOf(String(active.id))
    const to = columnOf(String(over.id))
    if (!from || !to || from === to) return

    setColumns((prev) => {
      const moved = prev[from].find((t) => t.id === active.id)
      if (!moved) return prev
      const overIndex = prev[to].findIndex((t) => t.id === over.id)
      const insertAt = overIndex >= 0 ? overIndex : prev[to].length
      return {
        ...prev,
        [from]: prev[from].filter((t) => t.id !== active.id),
        [to]: [
          ...prev[to].slice(0, insertAt),
          { ...moved, status: to },
          ...prev[to].slice(insertAt),
        ],
      }
    })
  }

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    const snapshot = beforeDrag
    setActiveId(null)
    setBeforeDrag(null)
    if (!over || !snapshot) return

    const activeIdStr = String(active.id)
    const destColumn = columnOf(activeIdStr)
    if (!destColumn) return

    // Finalize the within-column order (reorder against the hovered card).
    let next = columns
    const overColumn = columnOf(String(over.id))
    if (overColumn === destColumn) {
      const items = columns[destColumn]
      const oldIndex = items.findIndex((t) => t.id === activeIdStr)
      const newIndex = items.findIndex((t) => t.id === String(over.id))
      if (oldIndex !== -1 && newIndex !== -1 && oldIndex !== newIndex) {
        next = { ...columns, [destColumn]: arrayMove(items, oldIndex, newIndex) }
        setColumns(next)
      }
    }

    const sourceColumn = (Object.keys(snapshot) as TaskStatus[]).find((s) =>
      snapshot[s].some((t) => t.id === activeIdStr),
    )
    const moved = Object.values(next).flat().find((t) => t.id === activeIdStr)
    if (!moved || !sourceColumn) return

    const columnChanged = sourceColumn !== destColumn
    // Nothing to persist if neither the column nor the order changed.
    const beforeOrder = snapshot[destColumn]?.map((t) => t.id).join(",")
    const afterOrder = next[destColumn].map((t) => t.id).join(",")
    if (!columnChanged && beforeOrder === afterOrder) return

    const orderPayload = next[destColumn].map((t) => ({
      id: t.id,
      source: t.source,
    }))

    const fail = (message: string) => {
      setColumns(snapshot) // roll back the optimistic move/reorder
      toast.error(message)
    }

    let columnCommitted = false
    if (columnChanged) {
      const res = await tasksApi.updateStatus(activeIdStr, destColumn, moved.source)
      if (!res.success) {
        fail(
          res.message?.includes("Not allowed")
            ? "No tienes permiso para mover esta tarea."
            : "No se pudo mover la tarea. Inténtalo de nuevo.",
        )
        return
      }
      columnCommitted = true
    }

    const ordered = await tasksApi.reorder(orderPayload)
    if (!ordered.success) {
      // The column move (if any) is already saved; don't roll it back, only report
      // that the order didn't save — otherwise the UI would diverge from the backend.
      if (columnCommitted) {
        toast.error("Se movió la columna, pero no se pudo guardar el orden.")
      } else {
        fail("No se pudo guardar el orden. Inténtalo de nuevo.")
      }
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-60 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white">
        <p className="text-sm text-slate-500">Cargando tareas...</p>
      </div>
    )
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={collisionDetection}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
    >
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
        {TASK_STATUS_ORDER.map((status) => (
          <Column key={status} status={status} tasks={columns[status]} />
        ))}
      </div>
      <DragOverlay>{activeTask ? <TaskCard task={activeTask} /> : null}</DragOverlay>
    </DndContext>
  )
}
