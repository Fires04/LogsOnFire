"""Import all models here so Alembic autogenerate and Base.metadata.create_all
see the full schema regardless of which module happens to be imported first.
"""
from app.models.agent import Agent
from app.models.audit import AuditLog
from app.models.dashboard import Dashboard, DashboardPanel
from app.models.log_source import LogSource
from app.models.saved_filter import SavedFilter
from app.models.user import Permission, ResourceGrant, Role, User

__all__ = [
    "Agent",
    "AuditLog",
    "Dashboard",
    "DashboardPanel",
    "LogSource",
    "SavedFilter",
    "Permission",
    "ResourceGrant",
    "Role",
    "User",
]
