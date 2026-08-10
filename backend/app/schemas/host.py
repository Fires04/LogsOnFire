from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ConnectionType = Literal["local", "ssh"]
AuthType = Literal["password", "private_key"]


class HostCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    connection_type: ConnectionType
    hostname: str | None = None
    port: int = 22
    ssh_username: str | None = None
    auth_type: AuthType | None = None
    password: str | None = None
    private_key: str | None = None
    private_key_passphrase: str | None = None

    @model_validator(mode="after")
    def _validate_ssh_fields(self) -> "HostCreate":
        if self.connection_type == "ssh":
            if not self.hostname:
                raise ValueError("hostname is required for ssh hosts")
            if not self.ssh_username:
                raise ValueError("ssh_username is required for ssh hosts")
            if self.auth_type == "password" and not self.password:
                raise ValueError("password is required when auth_type is 'password'")
            if self.auth_type == "private_key" and not self.private_key:
                raise ValueError("private_key is required when auth_type is 'private_key'")
            if self.auth_type is None:
                raise ValueError("auth_type is required for ssh hosts")
        return self


class HostUpdate(BaseModel):
    name: str | None = None
    hostname: str | None = None
    port: int | None = None
    ssh_username: str | None = None
    auth_type: AuthType | None = None
    password: str | None = None
    private_key: str | None = None
    private_key_passphrase: str | None = None


class HostOut(BaseModel):
    id: str
    name: str
    connection_type: ConnectionType
    hostname: str | None
    port: int
    ssh_username: str | None
    auth_type: AuthType | None
    has_password: bool
    has_private_key: bool

    model_config = {"from_attributes": True}


class TestConnectionResult(BaseModel):
    success: bool
    message: str
