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
        },
        users: {
          base: "/api/v1/users",
        },
        dashboard: {
          summary: "/api/v1/dashboard/summary",
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
      },
      users: {
        base: "/api/users",
      },
      dashboard: {
        summary: "/api/dashboard",
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
