"""Shared slowapi Limiter instance.

Lives in its own module (rather than app/main.py) so route modules like
api/routes/auth.py can import it without creating an import cycle with the
app factory that wires everything together.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
