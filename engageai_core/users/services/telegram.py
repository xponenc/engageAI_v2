import os

import qrcode
import uuid

from django.conf import settings

from users.models import TelegramProfile


def generate_invite(user):
    code = uuid.uuid4().hex[:64]  # короткий уникальный код
    profile, created = TelegramProfile.objects.get_or_create(user=user)
    if created:
        profile.invite_code = code
        profile.save()

    bot_username = "DPO_Assistant_bot"
    link = f"https://t.me/{bot_username}?start=registration:{code}"
    # link = f"tg://resolve?domain={bot_username}&start=registration:{code}"

    qr_dir = os.path.join(settings.MEDIA_ROOT, "users", f"user-id-{user.id}")
    os.makedirs(qr_dir, exist_ok=True)
    qr_path = os.path.join(qr_dir, f"telegram-invite-{user.pk}.png")

    if os.path.exists(qr_path):
        os.remove(qr_path)

    img = qrcode.make(link)
    img.save(qr_path)
    return link, qr_path
