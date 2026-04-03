"""
Shared asyncpg pool for Postgres via the Cloud SQL Python Connector.

Required:
  - POSTGRES_INSTANCE_CONNECTION_NAME=project:region:instance
    (or POSTGRES_HOST=/cloudsql/project:region:instance for backward compatibility)

The connector opens an encrypted tunnel to Cloud SQL using Application Default Credentials,
so no IP allowlist is needed. Authentication to Postgres itself uses POSTGRES_USER/PASSWORD.

  - On Cloud Run: ADC resolves automatically from the attached service account.
  - Locally: set GOOGLE_APPLICATION_CREDENTIALS to a service account key file.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import asyncpg
from google.cloud.sql.connector import Connector, create_async_connector

_pool: Optional[asyncpg.Pool] = None
_connector: Optional[Connector] = None

# asyncpg passes these into the pool's connect callback; Cloud SQL ignores them.
_SKIP_CONNECT_KWARGS = frozenset({"loop", "connection_class", "record_class"})

def _instance_connection_name() -> str:
    explicit = os.getenv("POSTGRES_INSTANCE_CONNECTION_NAME", "").strip()
    if explicit:
        return explicit

    host = os.getenv("POSTGRES_HOST", "").strip()
    if host.startswith("/cloudsql/"):
        return host[len("/cloudsql/") :]

    # Historical: some envs used POSTGRES_HOST directly as instance name
    if host and ":" in host and not host.startswith("/"):
        return host

    raise KeyError(
        "Missing Cloud SQL instance connection name. Set POSTGRES_INSTANCE_CONNECTION_NAME "
        "or POSTGRES_HOST=/cloudsql/project:region:instance."
    )


async def get_pool() -> asyncpg.Pool:
    global _pool, _connector
    if _pool is None:
        instance = _instance_connection_name()
        db       = os.environ["POSTGRES_DB"]
        user     = os.environ["POSTGRES_USER"]
        password = os.environ["POSTGRES_PASSWORD"]

        _connector = await create_async_connector()

        async def _getconn(*_args, **_kwargs):
            extra = {k: v for k, v in _kwargs.items() if k not in _SKIP_CONNECT_KWARGS}
            return await _connector.connect_async(
                instance,
                "asyncpg",
                user=user,
                password=password,
                db=db,
                **extra,
            )

        _pool = await asyncpg.create_pool(
            connect=_getconn,
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool() -> None:
    global _pool, _connector
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _connector is not None:
        await _connector.close_async()
        _connector = None
