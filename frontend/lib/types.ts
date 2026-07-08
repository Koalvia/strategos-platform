// Domain Types

export interface User {
  id: string
  name: string
  email: string
  password: string
  emailVerified: boolean
  verificationToken?: string
  resetToken?: string
  resetTokenExpiry?: number
  createdAt: string
}

// Backend API response types (snake_case)
export interface ListResponse {
  id: number
  user_id: number
  name: string
  description?: string | null
  color: string
  task_count?: number
  completed_count?: number
  created_at: string
  updated_at: string
}

// Frontend types (camelCase for easier use in components)
export interface List {
  id: string
  userId: string
  title: string
  description?: string
  color: string
  taskCount?: number
  completedCount?: number
  createdAt: string
  updatedAt: string
}

// Backend API response types (snake_case)
export interface TaskResponse {
  id: number
  list_id: number
  title: string
  description?: string | null
  completed: boolean
  priority: "low" | "medium" | "high"
  due_date?: string | null
  created_at: string
  updated_at: string
}

// Frontend types (camelCase for easier use in components)
export interface Task {
  id: string
  listId: string
  title: string
  description?: string
  completed: boolean
  priority: "low" | "medium" | "high"
  dueDate?: string
  createdAt: string
  updatedAt: string
}

// Customer status matches the Business Central vocabulary the backend returns.
export type CustomerStatus = "Activo" | "Inactivo"

// Backend API response type (from GET /api/v1/customers)
export interface CustomerResponse {
  name: string
  nif: string
  entity_type: string
  responsible: string
  project_count: number
  status: CustomerStatus
}

// Frontend type (camelCase for easier use in components)
export interface Customer {
  name: string
  nif: string
  entityType: string
  responsible: string
  projectCount: number
  status: CustomerStatus
}

// Project status matches the Business Central vocabulary the backend returns.
export type ProjectStatus = "Activo" | "Inactivo"

// Backend API response types (from GET /api/v1/projects)
export interface ProjectCustomerResponse {
  id: string
  name: string
}

export interface ProjectResponse {
  id: string
  name: string
  customer: ProjectCustomerResponse
  project_type: string
  entity_type: string
  responsible: string
  technician: string
  has_certificate: boolean
  certificate_expiry?: string | null
  filing_date?: string | null
  status: ProjectStatus
}

// Frontend type (camelCase for easier use in components)
export interface Project {
  id: string
  name: string
  customer: ProjectCustomerResponse
  projectType: string
  entityType: string
  responsible: string
  technician: string
  hasCertificate: boolean
  certificateExpiry?: string
  filingDate?: string
  status: ProjectStatus
}

// Derived due state for an obligation instance (values mirror the UI badges).
export type ObligationStatus = "Vencido" | "Próximo" | "Al día"

interface ObligationEntityRef {
  id: string
  name: string
}

interface ObligationTypeRef {
  code: string
  name: string
}

// Backend API response type (from GET /api/v1/obligations)
export interface ProjectObligationResponse {
  id: string
  obligation: ObligationTypeRef
  project: ObligationEntityRef
  client: ObligationEntityRef
  subject: boolean
  due_date: string
  submission_date?: string | null
  status: ObligationStatus
}

// Frontend type (camelCase for easier use in components)
export interface ProjectObligation {
  id: string
  obligation: ObligationTypeRef
  project: ObligationEntityRef
  client: ObligationEntityRef
  subject: boolean
  dueDate: string
  submissionDate?: string
  status: ObligationStatus
}

export interface AuthResponse {
  success: boolean
  message?: string
  user?: Omit<User, "password">
  token?: string
}

export interface ApiResponse<T = any> {
  success: boolean
  data?: T
  message?: string
  error?: string
}

// Transformation utilities to convert between backend and frontend types
export function transformListResponse(backendList: ListResponse): List {
  return {
    id: String(backendList.id),
    userId: String(backendList.user_id),
    title: backendList.name,
    description: backendList.description || undefined,
    color: backendList.color,
    taskCount: backendList.task_count,
    completedCount: backendList.completed_count,
    createdAt: backendList.created_at,
    updatedAt: backendList.updated_at,
  }
}

export function transformCustomerResponse(backendCustomer: CustomerResponse): Customer {
  return {
    name: backendCustomer.name,
    nif: backendCustomer.nif,
    entityType: backendCustomer.entity_type,
    responsible: backendCustomer.responsible,
    projectCount: backendCustomer.project_count,
    status: backendCustomer.status,
  }
}

export function transformProjectResponse(backendProject: ProjectResponse): Project {
  return {
    id: backendProject.id,
    name: backendProject.name,
    customer: backendProject.customer,
    projectType: backendProject.project_type,
    entityType: backendProject.entity_type,
    responsible: backendProject.responsible,
    technician: backendProject.technician,
    hasCertificate: backendProject.has_certificate,
    certificateExpiry: backendProject.certificate_expiry || undefined,
    filingDate: backendProject.filing_date || undefined,
    status: backendProject.status,
  }
}

export function transformProjectObligationResponse(
  backendObligation: ProjectObligationResponse,
): ProjectObligation {
  return {
    id: backendObligation.id,
    obligation: backendObligation.obligation,
    project: backendObligation.project,
    client: backendObligation.client,
    subject: backendObligation.subject,
    dueDate: backendObligation.due_date,
    submissionDate: backendObligation.submission_date || undefined,
    status: backendObligation.status,
  }
}

export function transformTaskResponse(backendTask: TaskResponse): Task {
  return {
    id: String(backendTask.id),
    listId: String(backendTask.list_id),
    title: backendTask.title,
    description: backendTask.description || undefined,
    completed: backendTask.completed,
    priority: backendTask.priority,
    dueDate: backendTask.due_date || undefined,
    createdAt: backendTask.created_at,
    updatedAt: backendTask.updated_at,
  }
}
