# backend/auth.py
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

from users.models import UserProfile, TelegramProfile  # Django ORM через django.setup()

router = APIRouter()

INTERNAL_KEY = os.getenv("INTERNAL_KEY")


class TelegramAuthRequest(BaseModel):
    telegram_id: int
    invite_code: Optional[str] = None  # payload из /start


@router.post("/auth/telegram")
async def telegram_auth(
    payload: TelegramAuthRequest,
    x_internal_key: str = Header(None)
):
    # Проверка внутреннего ключа
    if x_internal_key != INTERNAL_KEY:
        raise HTTPException(status_code=403, detail="Invalid internal key")

    telegram_id = payload.telegram_id
    invite_code = payload.invite_code

    # Попытка найти профиль по invite_code
    profile_data = {"registered": False, "name": None}

    if invite_code:
        try:
            profile = TelegramProfile.objects.get(invite_code=invite_code)
            # Привязываем telegram_id к пользователю
            profile.telegram_id = telegram_id
            profile.save()
            profile_data["registered"] = True
            profile_data["name"] = profile.user.get_full_name() or profile.user.username
        except TelegramProfile.DoesNotExist:
            profile_data["registered"] = False

    return {"profile": profile_data}
