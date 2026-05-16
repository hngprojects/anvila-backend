import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, List

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.core.base.services import Service
from api.db.database import get_db
from api.utils.settings import settings
from api.v1.models import Organisation, ResetPasswordToken, User
from api.v1.models.associations import user_organisation_association
from api.v1.schemas.request_password_reset import (
    OrganizationData,
    ResetPasswordRequest,
    ResetPasswordSuccesful,
    UserData,
)
from api.v1.services.user import user_service

PASSWORD_RESET_TOKEN_TTL_MINUTES = 5


class RequestPasswordService(Service):
    def fetch(self, email: str, db: Annotated[Session, Depends(get_db)]):
        return db.query(User).filter_by(email=email).one_or_none()

    def create(self, user: User, db: Annotated[Session, Depends(get_db)]) -> str:
        # Delete any existing tokens for this user so there is only ever one active.
        db.query(ResetPasswordToken).filter_by(user_id=user.id).delete()

        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=PASSWORD_RESET_TOKEN_TTL_MINUTES
        )

        reset_token = ResetPasswordToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        db.add(reset_token)
        db.commit()
        return raw

    def update(
        self,
        reset_password_data: ResetPasswordRequest,
        db: Annotated[Session, Depends(get_db)],
    ):
        token_hash = hashlib.sha256(
            reset_password_data.reset_token.encode()
        ).hexdigest()

        user_token = (
            db.query(ResetPasswordToken)
            .filter_by(token_hash=token_hash)
            .one_or_none()
        )

        if not user_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="reset token invalid",
            )

        if user_token.used_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="reset token already used",
            )

        now = datetime.now(timezone.utc)
        if user_token.expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="reset token invalid",
            )

        user = db.query(User).filter_by(id=user_token.user_id).one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

        user.password = user_service.hash_password(reset_password_data.new_password)
        user_token.used_at = now
        db.commit()

        access_token = user_service.create_access_token(user_token.user_id)
        refresh_token = user_service.create_refresh_token(user_token.user_id)

        organizations = (
            db.query(Organisation)
            .join(
                user_organisation_association,
                Organisation.id == user_organisation_association.c.organisation_id,
            )
            .filter(user_organisation_association.c.user_id == user.id)
            .all()
        )

        self.delete(user_token, db)
        return (
            self.get_reset_token_response(access_token, user, organizations),
            refresh_token,
        )

    def fetch_all(self):
        pass

    def delete(
        self,
        user_token: ResetPasswordToken,
        db: Annotated[Session, Depends(get_db)],
    ):
        db.delete(user_token)
        db.commit()

    def get_reset_token_response(
        self, access_token: str, user: User, organization: Organisation
    ):
        organization_data: List[OrganizationData] = [
            OrganizationData.model_validate(org, from_attributes=True)
            for org in organization
        ]
        user_data = UserData.model_validate(user, from_attributes=True)
        return ResetPasswordSuccesful(
            message="password successfully reset",
            status_code=status.HTTP_201_CREATED,
            access_token=access_token,
            data={"user": user_data, "organisations": organization_data},
        )


reset_password_service = RequestPasswordService()
