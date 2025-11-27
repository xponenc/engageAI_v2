from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
import os

router = APIRouter()

INTERNAL_KEY = os.getenv("INTERNAL_KEY")


class RegistrationRequest(BaseModel):
    telegram_id: int
    registration_code: str


@router.post("/registration")
async def registration(
    payload: RegistrationRequest,
    x_internal_key: str = Header(None)
):
    if x_internal_key != INTERNAL_KEY:
        raise HTTPException(status_code=403, detail="Invalid internal key")

    # Здесь твоя Django-логика проверки кода
    from users.models import RegistrationCode

    try:
        code: RegistrationCode = RegistrationCode.objects.get(code=payload.registration_code)
    except RegistrationCode.DoesNotExist:
        return {"ok": False, "detail": "Invalid registration code"}

    user = code.user
    user.telegram_id = payload.telegram_id
    user.save()

    return {"ok": True}
