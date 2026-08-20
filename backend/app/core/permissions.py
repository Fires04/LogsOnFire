"""Permission code constants shared between seeding and route guards."""
from __future__ import annotations

AGENT_READ = "agent:read"
AGENT_WRITE = "agent:write"
LOG_SOURCE_READ = "log_source:read"
LOG_SOURCE_WRITE = "log_source:write"
LOG_VIEW = "log:view"
DASHBOARD_READ = "dashboard:read"
DASHBOARD_WRITE = "dashboard:write"
USER_MANAGE = "user:manage"

ALL_PERMISSIONS = [
    AGENT_READ,
    AGENT_WRITE,
    LOG_SOURCE_READ,
    LOG_SOURCE_WRITE,
    LOG_VIEW,
    DASHBOARD_READ,
    DASHBOARD_WRITE,
    USER_MANAGE,
]

ADMIN_ROLE = "admin"
