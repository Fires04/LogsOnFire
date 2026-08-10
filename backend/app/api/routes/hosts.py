from __future__ import annotations

import logging
import posixpath

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import record as audit_record
from app.core.permissions import HOST_READ, HOST_WRITE
from app.database import get_db
from app.models.host import Host, HostCredential
from app.models.user import User
from app.providers.registry import get_provider
from app.schemas.browse import BrowseResponse, DirEntryOut
from app.schemas.host import HostCreate, HostOut, HostUpdate, TestConnectionResult
from app.security.crypto import encrypt_str
from app.security.deps import require_permission
from app.ssh.connect import host_key_line, key_fingerprint, open_ssh_connection
from app.ssh.exceptions import SshError
from app.ssh.pool import get_ssh_pool

router = APIRouter(prefix="/api/hosts", tags=["hosts"])
logger = logging.getLogger("logsonfire.hosts")


def _to_out(host: Host) -> HostOut:
    cred = host.credential
    return HostOut(
        id=host.id,
        name=host.name,
        connection_type=host.connection_type,
        hostname=host.hostname,
        port=host.port,
        ssh_username=host.ssh_username,
        auth_type=host.auth_type,
        has_password=bool(cred and cred.encrypted_password),
        has_private_key=bool(cred and cred.encrypted_private_key),
    )


async def _get_host_or_404(db: AsyncSession, host_id: str) -> Host:
    result = await db.execute(
        select(Host).options(selectinload(Host.credential)).where(Host.id == host_id)
    )
    host = result.scalar_one_or_none()
    if host is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Host not found")
    return host


@router.get("", response_model=list[HostOut])
async def list_hosts(
    db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(HOST_READ))
) -> list[HostOut]:
    result = await db.execute(select(Host).options(selectinload(Host.credential)).order_by(Host.name))
    return [_to_out(h) for h in result.scalars()]


@router.get("/{host_id}", response_model=HostOut)
async def get_host(
    host_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(HOST_READ))
) -> HostOut:
    host = await _get_host_or_404(db, host_id)
    return _to_out(host)


@router.post("", response_model=HostOut, status_code=status.HTTP_201_CREATED)
async def create_host(
    payload: HostCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(HOST_WRITE)),
) -> HostOut:
    host = Host(
        name=payload.name,
        connection_type=payload.connection_type,
        hostname=payload.hostname,
        port=payload.port,
        ssh_username=payload.ssh_username,
        auth_type=payload.auth_type,
        created_by=user.id,
    )
    db.add(host)
    await db.flush()

    if payload.connection_type == "ssh":
        cred = HostCredential(host_id=host.id)
        if payload.password:
            cred.encrypted_password = encrypt_str(payload.password)
        if payload.private_key:
            cred.encrypted_private_key = encrypt_str(payload.private_key)
        if payload.private_key_passphrase:
            cred.encrypted_private_key_passphrase = encrypt_str(payload.private_key_passphrase)
        db.add(cred)

    await db.commit()
    await audit_record(
        db, user_id=user.id, event_type="host_created", target_type="host", target_id=host.id, detail={"name": host.name}
    )
    host = await _get_host_or_404(db, host.id)
    return _to_out(host)


@router.patch("/{host_id}", response_model=HostOut)
async def update_host(
    host_id: str,
    payload: HostUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission(HOST_WRITE)),
) -> HostOut:
    host = await _get_host_or_404(db, host_id)

    for field in ("name", "hostname", "port", "ssh_username", "auth_type"):
        value = getattr(payload, field)
        if value is not None:
            setattr(host, field, value)

    if payload.password or payload.private_key or payload.private_key_passphrase:
        cred = host.credential or HostCredential(host_id=host.id)
        if payload.password:
            cred.encrypted_password = encrypt_str(payload.password)
        if payload.private_key:
            cred.encrypted_private_key = encrypt_str(payload.private_key)
        if payload.private_key_passphrase:
            cred.encrypted_private_key_passphrase = encrypt_str(payload.private_key_passphrase)
        if cred.id is None:
            db.add(cred)

    await db.commit()
    # Connection details or credentials may have changed — a pooled
    # connection opened under the old ones must not keep being reused.
    await get_ssh_pool().evict(host_id)
    await audit_record(db, user_id=user.id, event_type="host_updated", target_type="host", target_id=host_id)
    host = await _get_host_or_404(db, host_id)
    return _to_out(host)


@router.delete("/{host_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_host(
    host_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_permission(HOST_WRITE))
) -> None:
    host = await _get_host_or_404(db, host_id)
    name = host.name
    await db.delete(host)
    await db.commit()
    await get_ssh_pool().evict(host_id)
    await audit_record(
        db, user_id=user.id, event_type="host_deleted", target_type="host", target_id=host_id, detail={"name": name}
    )


@router.post("/{host_id}/test-connection", response_model=TestConnectionResult)
async def test_connection(
    host_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_permission(HOST_WRITE))
) -> TestConnectionResult:
    host = await _get_host_or_404(db, host_id)

    if host.connection_type == "local":
        return TestConnectionResult(success=True, message="Local host — no connection needed.")

    first_trust = host.known_host_key is None
    try:
        conn = await open_ssh_connection(host, host.credential)
    except SshError as exc:
        await audit_record(
            db, user_id=user.id, event_type="test_connection_failed", target_type="host", target_id=host_id,
            detail={"message": str(exc)},
        )
        return TestConnectionResult(success=False, message=str(exc))

    try:
        server_key = conn.get_server_host_key()
        fingerprint = key_fingerprint(server_key) if server_key else "unknown"
        if first_trust and server_key is not None:
            host.known_host_key = host_key_line(host.hostname, host.port, server_key)
            await db.commit()
            message = f"Connected. Host key trusted on first use (SHA256 fingerprint: {fingerprint})."
        else:
            message = f"Connected. Host key fingerprint: {fingerprint}."
        await audit_record(
            db, user_id=user.id, event_type="test_connection_succeeded", target_type="host", target_id=host_id,
            detail={"fingerprint": fingerprint},
        )
        return TestConnectionResult(success=True, message=message)
    finally:
        conn.close()
        await conn.wait_closed()


@router.get("/{host_id}/browse", response_model=BrowseResponse)
async def browse_host(
    host_id: str,
    path: str | None = Query(None, description="Directory to list; defaults to the host's home/root"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission(HOST_READ)),
) -> BrowseResponse:
    """Powers the log-source file picker: list one directory's contents on
    the given host (local filesystem or over SFTP), so a file can be
    selected directly instead of typed by hand.
    """
    host = await _get_host_or_404(db, host_id)
    provider = get_provider(host)

    target = path
    try:
        if not target:
            target = await provider.default_browse_path()
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a 500
        return BrowseResponse(path=path or "/", parent=None, entries=[], truncated=False, error=str(exc))

    # Computed unconditionally (not just on the success path below) — even
    # when listing this directory fails (e.g. permission denied), we still
    # know its parent from the path alone, and the "Up" button needs that to
    # let the user back out of a directory they can't read.
    normalized = target.rstrip("/") or "/"
    parent = posixpath.dirname(normalized) if normalized != "/" else None

    try:
        entries, truncated = await provider.list_directory(target)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a 500
        return BrowseResponse(path=normalized, parent=parent, entries=[], truncated=False, error=str(exc))

    return BrowseResponse(
        path=normalized,
        parent=parent,
        entries=[
            DirEntryOut(
                name=e.name,
                path=e.path,
                is_dir=e.is_dir,
                size=e.size,
                mtime=e.mtime,
                permissions=e.permissions,
                readable=e.readable,
            )
            for e in entries
        ],
        truncated=truncated,
    )


@router.post("/{host_id}/reset-trust", response_model=TestConnectionResult)
async def reset_trust(
    host_id: str, db: AsyncSession = Depends(get_db), _user: User = Depends(require_permission(HOST_WRITE))
) -> TestConnectionResult:
    """Forget the pinned SSH host key, so the next connection re-trusts on first use.

    Use this after a deliberate server-side host key change (reimage, migration) —
    never as a routine way to dismiss a mismatch warning without checking why it changed.
    """
    host = await _get_host_or_404(db, host_id)
    host.known_host_key = None
    await db.commit()
    await get_ssh_pool().evict(host_id)
    return TestConnectionResult(success=True, message="Host key trust reset. It will be re-pinned on next connect.")
