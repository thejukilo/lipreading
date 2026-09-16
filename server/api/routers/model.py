"""Model selection + info: switch Speak between the base and personal model."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import PersonalModel, TrainingSample, User
from ..schemas import ModelInfoOut, ModelSelectIn

router = APIRouter(prefix="/api/model", tags=["model"])


def _latest_personal(db: Session, user_id: str) -> PersonalModel | None:
    return db.scalar(select(PersonalModel).where(PersonalModel.user_id == user_id)
                     .order_by(PersonalModel.created_at.desc()))


def _info(db: Session, user: User) -> ModelInfoOut:
    pm = _latest_personal(db, user.id)
    total = int(db.scalar(select(func.count()).select_from(TrainingSample)
                          .where(TrainingSample.user_id == user.id)) or 0)
    distinct = int(db.scalar(select(func.count(func.distinct(TrainingSample.phrase)))
                             .where(TrainingSample.user_id == user.id)) or 0)
    return ModelInfoOut(
        active="personal" if user.active_model_id else "base",
        has_personal=pm is not None,
        trained_at=pm.created_at if pm else None,
        n_samples=pm.n_samples if pm else None,
        total_clips=total,
        distinct_phrases=distinct,
    )


@router.get("/info", response_model=ModelInfoOut)
def model_info(user: User = Depends(get_current_user),
               db: Session = Depends(get_db)) -> ModelInfoOut:
    return _info(db, user)


@router.post("/select", response_model=ModelInfoOut)
def model_select(body: ModelSelectIn, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)) -> ModelInfoOut:
    if body.use_personal:
        pm = _latest_personal(db, user.id)
        if pm is None:
            raise HTTPException(status_code=400, detail="no personalized model yet — train one first")
        user.active_model_id = pm.id
    else:
        user.active_model_id = None
    db.add(user)
    db.commit()
    return _info(db, user)
