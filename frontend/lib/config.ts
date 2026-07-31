export const config = {
  app: {
    name: "Strategos",
    description: "Modern TODO list platform",
  },
  api: {
    // Real backend API configuration
    baseUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    apiKey: process.env.NEXT_PUBLIC_API_KEY || "PI1u-i-6i2pGeIi9q6OOaYYLc7BnjCHzJ58m0NEaIrM",
    endpoints: {
      // Backend API endpoints (v1)
      backend: {
        auth: {
          register: "/api/v1/auth/register",
          login: "/api/v1/auth/login",
          logout: "/api/v1/auth/logout",
          verifyEmail: "/api/v1/auth/verify-email",
          forgotPassword: "/api/v1/auth/forgot-password",
          resetPassword: "/api/v1/auth/reset-password",
          me: "/api/v1/auth/me",
        },
        tasks: {
          base: "/api/v1/tasks",
        },
        customers: {
          base: "/api/v1/customers",
          byId: (id: string) => `/api/v1/customers/${id}`,
        },
        projects: {
          base: "/api/v1/projects",
          byId: (id: string) => `/api/v1/projects/${id}`,
        },
        obligations: {
          base: "/api/v1/obligations",
          catalog: "/api/v1/obligations/catalog",
          projects: "/api/v1/obligations/projects",
        },
        users: {
          base: "/api/v1/users",
        },
        dashboard: {
          activeProjects: "/api/v1/dashboard/active-projects",
          activeCustomers: "/api/v1/dashboard/active-customers",
          pendingTasks: "/api/v1/dashboard/pending-tasks",
          upcomingObligationsCount: "/api/v1/dashboard/upcoming-obligations-count",
          obligations: "/api/v1/dashboard/obligations",
          billing: "/api/v1/dashboard/billing",
        },
        bopa: {
          documents: "/api/v1/bopa/documents",
          documentFilters: "/api/v1/bopa/documents/filters",
          documentById: (id: string) => `/api/v1/bopa/documents/${id}`,
        },
        alerts: {
          base: "/api/v1/alerts",
          unreadCount: "/api/v1/alerts/unread-count",
          markAllRead: "/api/v1/alerts/mark-all-read",
          byId: (id: string) => `/api/v1/alerts/${id}`,
        },
      },
      // Frontend API routes (proxy to backend)
      auth: {
        register: "/api/auth/register",
        login: "/api/auth/login",
        logout: "/api/auth/logout",
        verifyEmail: "/api/auth/verify-email",
        forgotPassword: "/api/auth/forgot-password",
        resetPassword: "/api/auth/reset-password",
        me: "/api/auth/me",
      },
      tasks: {
        base: "/api/tasks",
      },
      customers: {
        base: "/api/customers",
      },
      projects: {
        base: "/api/projects",
      },
      obligations: {
        base: "/api/obligations",
        // Same route, asked for the "Proyecto" filter's option list instead of a
        // page of rows — see the `options` param in app/api/obligations/route.ts.
        projectOptions: "/api/obligations?options=projects",
      },
      users: {
        base: "/api/users",
      },
      // One route per dashboard widget, so the page loads them in parallel and
      // a slow or failing widget never blocks the others.
      dashboard: {
        activeProjects: "/api/dashboard/active-projects",
        activeCustomers: "/api/dashboard/active-customers",
        pendingTasks: "/api/dashboard/pending-tasks",
        upcomingObligationsCount: "/api/dashboard/upcoming-obligations-count",
        obligations: "/api/dashboard/obligations",
        billing: "/api/dashboard/billing",
      },
      bopa: {
        documents: "/api/bopa/documents",
        documentFilters: "/api/bopa/documents/filters",
      },
      alerts: {
        base: "/api/alerts",
        unreadCount: "/api/alerts/unread-count",
        markAllRead: "/api/alerts/mark-all-read",
      },
    },
  },
  routes: {
    home: "/",
    login: "/login",
    register: "/register",
    verifyEmail: "/verify-email",
    forgotPassword: "/forgot-password",
    resetPassword: "/reset-password",
  },
} as const
