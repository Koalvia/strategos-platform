from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domains.auth.models import User
from app.domains.auth.utils import get_verified_user
from app.domains.tasks.schemas import (
    MessageResponse,
    PriorityEnum,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
)
from app.domains.tasks.service import TasksService

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("", response_model=List[TaskResponse])
def get_tasks(
    list_id: int = Query(..., description="ID of the list to get tasks from"),
    completed: Optional[bool] = Query(None, description="Filter by completion status"),
    priority: Optional[PriorityEnum] = Query(None, description="Filter by priority"),
    due_after: Optional[date] = Query(
        None, description="Only tasks whose due_date is on or after this date (YYYY-MM-DD)"
    ),
    due_before: Optional[date] = Query(
        None, description="Only tasks whose due_date is on or before this date (YYYY-MM-DD)"
    ),
    overdue: Optional[bool] = Query(
        None, description="When true, only incomplete tasks whose due_date is before today"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user)
):
    """
    Get all tasks for a specific list. Optional filters by completion status,
    priority, due-date range and overdue status.

    - **list_id**: Required. The ID of the list to get tasks from
    - **completed**: Optional. Filter tasks by completion status (true/false)
    - **priority**: Optional. Filter tasks by priority (low/medium/high)
    - **due_after**: Optional. Only tasks whose due_date is on or after this date
    - **due_before**: Optional. Only tasks whose due_date is on or before this date
    - **overdue**: Optional. When true, only incomplete tasks whose due_date is
      before today (server date)

    When a due-date bound is provided, tasks without a due_date are excluded.
    Tasks with a null due_date are never considered overdue.
    """
    tasks_service = TasksService(db)
    return tasks_service.get_tasks_by_list(
        list_id, current_user.id, completed, priority, due_after, due_before, overdue
    )

@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user)
):
    """
    Get a specific task by ID.
    """
    tasks_service = TasksService(db)
    return tasks_service.get_task_by_id(task_id, current_user.id)

@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    task_data: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user)
):
    """
    Create a new task in a list.

    The list must belong to the authenticated user.
    """
    tasks_service = TasksService(db)
    return tasks_service.create_task(task_data, current_user.id)

@router.put("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: int,
    task_data: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user)
):
    """
    Update an existing task. Only provided fields will be updated.

    Can be used to update title, description, priority, due_date, or completion status.
    """
    tasks_service = TasksService(db)
    return tasks_service.update_task(task_id, task_data, current_user.id)

@router.delete("/{task_id}", response_model=MessageResponse)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_verified_user)
):
    """
    Delete a task.
    """
    tasks_service = TasksService(db)
    tasks_service.delete_task(task_id, current_user.id)
    return {"message": "Task deleted successfully"}
