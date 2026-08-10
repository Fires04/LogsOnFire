import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './lib/auth'
import AuthGuard from './components/AuthGuard'
import AppShell from './components/AppShell'
import LoginPage from './routes/LoginPage'
import HostsPage from './routes/HostsPage'
import HostDetailPage from './routes/HostDetailPage'
import DashboardsListPage from './routes/DashboardsListPage'
import DashboardEditPage from './routes/DashboardEditPage'
import DashboardViewPage from './routes/DashboardViewPage'
import LogViewPage from './routes/LogViewPage'

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route element={<AuthGuard />}>
          {/* Standalone views — no nav chrome, so "open in new tab" gives a clean window. */}
          <Route path="/view/log/:logSourceId" element={<LogViewPage />} />
          <Route path="/view/dashboard/:dashboardId" element={<DashboardViewPage />} />

          <Route element={<AppShell />}>
            <Route path="/hosts" element={<HostsPage />} />
            <Route path="/hosts/:hostId" element={<HostDetailPage />} />
            <Route path="/dashboards" element={<DashboardsListPage />} />
            <Route path="/dashboards/:dashboardId/edit" element={<DashboardEditPage />} />
            <Route path="/" element={<Navigate to="/hosts" replace />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  )
}
