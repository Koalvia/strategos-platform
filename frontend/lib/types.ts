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

// Task priority / status match the Business Central vocabulary the backend
// returns. Status names are the board columns rendered on the Tareas page.
export type TaskPriority = "Alta" | "Media" | "Baja"
export type TaskStatus = "Pendiente" | "En curso" | "Hecho"

interface TaskEntityRef {
  id: string
  name: string
}

// Backend API response type (from GET /api/v1/tasks). Tasks are sourced
// read-only from Business Central, so there are no local mutable columns.
export interface TaskResponse {
  id: string
  title: string
  project: TaskEntityRef
  assignee: TaskEntityRef
  priority: TaskPriority
  status: TaskStatus
  due_date: string
}

// Frontend type (camelCase for easier use in components)
export interface Task {
  id: string
  title: string
  project: TaskEntityRef
  assignee: TaskEntityRef
  priority: TaskPriority
  status: TaskStatus
  dueDate: string
}

// Customer status matches the Business Central vocabulary the backend returns.
export type CustomerStatus = "Activo" | "Inactivo"

// Backend API response type (from GET /api/v1/customers)
export interface CustomerResponse {
  id: string
  name: string
  nif: string
  entity_type: string
  responsible: string
  project_count: number
  status: CustomerStatus
}

// One page of the customers directory, plus an opaque continuation token
// (pass it back as `cursor` to fetch the next page; `null` once exhausted).
export interface CustomerPageResponse {
  items: CustomerResponse[]
  next_cursor: string | null
}

// Frontend type (camelCase for easier use in components)
export interface Customer {
  id: string
  name: string
  nif: string
  entityType: string
  responsible: string
  projectCount: number
  status: CustomerStatus
}

export interface CustomerPage {
  items: Customer[]
  nextCursor: string | null
}

// Project status matches the Business Central vocabulary the backend returns.
export type ProjectStatus = "Activo" | "Inactivo"

// Backend API response types (from GET /api/v1/projects)
export interface ProjectCustomerResponse {
  id: string
  name: string
}

// project_type/entity_type/has_certificate are nullable: the live Business
// Central client has no source field for them yet and leaves them null.
export interface ProjectResponse {
  id: string
  name: string
  customer: ProjectCustomerResponse
  project_type: string | null
  entity_type: string | null
  responsible: string
  technician: string
  has_certificate: boolean | null
  certificate_expiry?: string | null
  filing_date?: string | null
  status: ProjectStatus
}

// Frontend type (camelCase for easier use in components)
export interface Project {
  id: string
  name: string
  customer: ProjectCustomerResponse
  projectType: string | null
  entityType: string | null
  responsible: string
  technician: string
  hasCertificate: boolean | null
  certificateExpiry?: string
  filingDate?: string
  status: ProjectStatus
}

// One page of the projects directory, plus an opaque continuation token
// (pass it back as `cursor` to fetch the next page; `null` once exhausted).
export interface ProjectPageResponse {
  items: ProjectResponse[]
  next_cursor: string | null
}

export interface ProjectPage {
  items: Project[]
  nextCursor: string | null
}

// Derived due state for an obligation instance (values mirror the UI badges).
// "Sin fecha" covers instances with no due_date (e.g. live BC links that don't
// carry date fields yet) — see backend DerivedObligationStatus.undated.
export type ObligationStatus = "Vencido" | "Próximo" | "Al día" | "Sin fecha"

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
  subject: boolean | null
  due_date: string | null
  submission_date?: string | null
  status: ObligationStatus
}

// Frontend type (camelCase for easier use in components)
export interface ProjectObligation {
  id: string
  obligation: ObligationTypeRef
  project: ObligationEntityRef
  client: ObligationEntityRef
  subject: boolean | null
  dueDate: string | null
  submissionDate?: string
  status: ObligationStatus
}

// Users (Usuarios) directory. Identity stays local; the active-task count is
// derived from Business Central. Field names mirror the Usuarios table columns.

// Backend API response type (from GET /api/v1/users)
export interface UserDirectoryResponse {
  name: string
  role: string | null
  email: string
  active_tasks: number
}

// Frontend type (camelCase for easier use in components)
export interface UserDirectoryEntry {
  name: string
  role: string | null
  email: string
  activeTasks: number
}

// Dashboard summary. The landing screen is a pure aggregation view: the four KPI
// tiles plus the "Próximas obligaciones" and "Mis tareas de hoy" lists all come
// from a single GET /api/v1/dashboard/summary (see the dashboard domain).

// A KPI tile showing how many of a total are currently active.
export interface ActiveTotalKpi {
  active: number
  total: number
}

// A KPI tile showing how many of a total are still pending (not done).
export interface PendingTotalKpi {
  pending: number
  total: number
}

// A KPI tile that is a single count (obligations due within the window).
export interface CountKpi {
  count: number
}

// Billing, usage cost and logged hours for one project. snake_case ==
// camelCase here, so this shape is shared by the API response and the frontend.
export interface ProjectBilling {
  project_id: string
  project_name: string
  billed: number
  cost: number
  hours: number
}

// One customer with its per-project billing nested underneath — the row shape
// of the dashboard's unified billing accordion. ``net_billed`` is the
// authoritative per-customer net billing; ``cost``/``hours`` are rolled up from
// ``projects``. snake_case == camelCase, so shared by API response and frontend.
export interface CustomerBillingGroup {
  customer_id: string
  customer_name: string
  net_billed: number
  cost: number
  hours: number
  projects: ProjectBilling[]
}

// Backend API response type (from GET /api/v1/dashboard/summary). The two lists
// reuse the obligations / tasks response shapes; the financial section reuses
// the billing domain's shapes.
export interface DashboardSummaryResponse {
  proyectos_activos: ActiveTotalKpi
  obligaciones_proximas: CountKpi
  tareas_pendientes: PendingTotalKpi
  clientes_activos: ActiveTotalKpi
  proximas_obligaciones: ProjectObligationResponse[]
  mis_tareas_de_hoy: TaskResponse[]
  facturacion: CustomerBillingGroup[]
}

// Frontend type (camelCase for easier use in components)
export interface DashboardSummary {
  proyectosActivos: ActiveTotalKpi
  obligacionesProximas: CountKpi
  tareasPendientes: PendingTotalKpi
  clientesActivos: ActiveTotalKpi
  proximasObligaciones: ProjectObligation[]
  misTareasDeHoy: Task[]
  facturacion: CustomerBillingGroup[]
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
export function transformCustomerResponse(backendCustomer: CustomerResponse): Customer {
  return {
    id: backendCustomer.id,
    name: backendCustomer.name,
    nif: backendCustomer.nif,
    entityType: backendCustomer.entity_type,
    responsible: backendCustomer.responsible,
    projectCount: backendCustomer.project_count,
    status: backendCustomer.status,
  }
}

export function transformCustomerPageResponse(
  backendPage: CustomerPageResponse,
): CustomerPage {
  return {
    items: backendPage.items.map(transformCustomerResponse),
    nextCursor: backendPage.next_cursor,
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

export function transformProjectPageResponse(
  backendPage: ProjectPageResponse,
): ProjectPage {
  return {
    items: backendPage.items.map(transformProjectResponse),
    nextCursor: backendPage.next_cursor,
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

export function transformUserDirectoryResponse(
  backendUser: UserDirectoryResponse,
): UserDirectoryEntry {
  return {
    name: backendUser.name,
    role: backendUser.role,
    email: backendUser.email,
    activeTasks: backendUser.active_tasks,
  }
}

export function transformTaskResponse(backendTask: TaskResponse): Task {
  return {
    id: backendTask.id,
    title: backendTask.title,
    project: backendTask.project,
    assignee: backendTask.assignee,
    priority: backendTask.priority,
    status: backendTask.status,
    dueDate: backendTask.due_date,
  }
}

export function transformDashboardSummaryResponse(
  backendSummary: DashboardSummaryResponse,
): DashboardSummary {
  return {
    proyectosActivos: backendSummary.proyectos_activos,
    obligacionesProximas: backendSummary.obligaciones_proximas,
    tareasPendientes: backendSummary.tareas_pendientes,
    clientesActivos: backendSummary.clientes_activos,
    proximasObligaciones: backendSummary.proximas_obligaciones.map(
      transformProjectObligationResponse,
    ),
    misTareasDeHoy: backendSummary.mis_tareas_de_hoy.map(transformTaskResponse),
    facturacion: backendSummary.facturacion,
  }
}
