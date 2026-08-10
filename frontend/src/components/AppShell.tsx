import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../lib/auth'

export default function AppShell() {
  const { user, logout } = useAuth()

  return (
    <div className="app-shell">
      <nav className="app-nav">
        <span className="brand">
          <img src="/logo.png" alt="" className="brand-logo" />
          Logs On Fire
        </span>
        <NavLink to="/hosts" className={({ isActive }) => (isActive ? 'active' : '')}>
          Hosts
        </NavLink>
        <NavLink to="/dashboards" className={({ isActive }) => (isActive ? 'active' : '')}>
          Dashboards
        </NavLink>
        <span className="nav-spacer" />
        <span className="muted">{user?.email}</span>
        <button className="secondary" onClick={() => logout()}>
          Log out
        </button>
      </nav>
      <main>
        <Outlet />
      </main>
    </div>
  )
}
