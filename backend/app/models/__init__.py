"""Import all models here so Alembic autogenerate and Base.metadata.create_all
see the full schema regardless of which module happens to be imported first.
"""
from app.models.audit import AuditLog
from app.models.dashboard import Dashboard, DashboardPanel
from app.models.host import Host, HostCredential
from app.models.log_source import LogSource
from app.models.user import Permission, ResourceGrant, Role, User

__all__ = [
    "AuditLog",
    "Dashboard",
    "DashboardPanel",
    "Host",
    "HostCredential",
    "LogSource",
    "Permission",
    "ResourceGrant",
    "Role",
    "User",
]
