"use client"

import { useEffect, useState } from "react"
import { toast } from "sonner"

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { tasksApi } from "@/features/tasks/api"
import { TaskCard } from "./task-card"
import { TASK_STATUS_ORDER, TASK_STATUS_SHORT_LABEL } from "./status"
import type { Task, TaskStatus } from "@/lib/types"

interface ArchivedTasksProps {
  tasks: Task[]
  loading: boolean
}

// The archived view: a flat grid of archived cards, each with a "Desarchivar a…"
// select that moves the card back to a chosen board column.
export function ArchivedTasks({ tasks, loading }: ArchivedTasksProps) {
  const [items, setItems] = useState<Task[]>(tasks)

  useEffect(() => {
    setItems(tasks)
  }, [tasks])

  const unarchive = async (task: Task, to: TaskStatus) => {
    const snapshot = items
    setItems((prev) => prev.filter((t) => t.id !== task.id))
    const res = await tasksApi.updateStatus(task.id, to, task.source)
    if (!res.success) {
      setItems(snapshot)
      toast.error(
        res.message?.includes("Not allowed")
          ? "No tienes permiso para desarchivar esta tarea."
          : "No se pudo desarchivar la tarea. Inténtalo de nuevo.",
      )
    } else {
      toast.success(`Desarchivada a ${TASK_STATUS_SHORT_LABEL[to]}.`)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-60 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white">
        <p className="text-sm text-slate-500">Cargando tareas...</p>
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="flex min-h-60 items-center justify-center rounded-lg border border-dashed border-slate-300 bg-white">
        <p className="text-sm text-slate-500">Sin tareas archivadas.</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
      {items.map((task) => (
        <TaskCard
          key={task.id}
          task={task}
          action={
            <Select onValueChange={(value) => unarchive(task, value as TaskStatus)}>
              <SelectTrigger className="h-8 w-44 text-xs">
                <SelectValue placeholder="Desarchivar a…" />
              </SelectTrigger>
              <SelectContent>
                {TASK_STATUS_ORDER.map((option) => (
                  <SelectItem key={option} value={option}>
                    {TASK_STATUS_SHORT_LABEL[option]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          }
        />
      ))}
    </div>
  )
}
