#!/usr/bin/env python3
"""
Idempotent script to create or promote a super admin user.
Credentials are read from settings (ADMIN_EMAIL / ADMIN_PASSWORD in .env).

Usage:
    uv run python -m scripts.create_super_admin
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models.enums import UserPlan, UserProvider
from app.models.user import User
from app.core.security import hash_password


async def create_or_update_admin(session: AsyncSession, email: str, password: str) -> None:
    existing: User | None = await session.scalar(select(User).where(User.email == email))

    if existing:
        print(f"[~] User '{email}' already exists — ensuring super admin privileges.")
        existing.is_admin = True
        existing.is_super_admin = True
        existing.is_active = True
        existing.email_verified = True
        existing.password_hash = hash_password(password)
        await session.commit()
        print(f"[✓] User '{email}' is now a super admin.")
        return

    user = User(
        email=email,
        display_name="Admin",
        provider=UserProvider.EMAIL,
        password_hash=hash_password(password),
        email_verified=True,
        is_active=True,
        plan=UserPlan.FREE,
        is_admin=True,
        is_super_admin=True,
    )

    session.add(user)
    await session.commit()
    print(f"[✓] Super admin user '{email}' created successfully.")


async def main() -> None:
    email = settings.ADMIN_EMAIL
    password = settings.ADMIN_PASSWORD

    if not email or not password:
        print("[✗] ADMIN_EMAIL and ADMIN_PASSWORD must be set in your .env / config.")
        sys.exit(1)

    engine = create_async_engine(str(settings.DATABASE_URL))

    async with AsyncSession(engine) as session:
        await create_or_update_admin(session=session, email=email, password=password)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
