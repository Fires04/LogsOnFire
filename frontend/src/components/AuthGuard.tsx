import { Navigate, Outlet } from 'react-router-dom'
import { Center, Loader } from '@mantine/core'
import { useAuth } from '../lib/auth'

export default function AuthGuard() {
  const { user, loading } = useAuth()

  if (loading)
    return (
      <Center mih="100vh">
        <Loader color="flame" />
      </Center>
    )
  if (!user) return <Navigate to="/login" replace />
  return <Outlet />
}
