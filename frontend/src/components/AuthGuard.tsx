import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../lib/auth'

export default function AuthGuard() {
  const { user, loading } = useAuth()

  if (loading) return <div className="page-loading">Loading…</div>
  if (!user) return <Navigate to="/login" replace />
  return <Outlet />
}
