"use client"

import { useEffect, useState } from "react"

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { tasksApi } from "@/features/tasks/api"
import { TasksBoard } from "@/features/tasks/tasks-board"
import { TASK_STATUS_ORDER, TASK_STATUS_SHORT_LABEL } from "@/features/tasks/status"
import type { Task, TaskStatus } from "@/lib/types"

const ALL = "all"

export default function TareasPage() {
  const [status, setStatus] = useState<string>(ALL)
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true

    const loadBoard = async () => {
      setLoading(true)
      try {
        const result = await tasksApi.getBoard(
          status === ALL ? undefined : (status as TaskStatus),
        )
        if (!active) return
        setTasks(result.success && result.data ? result.data : [])
      } catch (error) {
        console.error("[Strategos] Load board error:", error)
        if (active) setTasks([])
      } finally {
        if (active) setLoading(false)
      }
    }

    loadBoard()
    return () => {
      active = false
    }
  }, [status])

  return (
    <div className="px-8 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-slate-900">Tareas</h1>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="h-11 bg-white sm:w-56">
            <SelectValue placeholder="Todos" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos</SelectItem>
            {TASK_STATUS_ORDER.map((option) => (
              <SelectItem key={option} value={option}>
                {TASK_STATUS_SHORT_LABEL[option]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="mt-6">
        <TasksBoard tasks={tasks} loading={loading} />
      </div>
    </div>
  )
}
