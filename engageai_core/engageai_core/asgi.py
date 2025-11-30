"""
ASGI config for engageai_core project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

# TODO открыть после интеграции Channels
# from channels.routing import ProtocolTypeRouter, URLRouter
# from channels.auth import AuthMiddlewareStack
# from channels.security.websocket import AllowedHostsOriginValidator
# import chat.routing  # ваше приложение с WebSocket

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'engageai_core.settings')

application = get_asgi_application()

# TODO открыть после интеграции Channels
# application = ProtocolTypeRouter({
#     "http": get_asgi_application(),  # Обработка HTTP-запросов
#     "websocket": AllowedHostsOriginValidator(  # Защита от CSRF
#         AuthMiddlewareStack(  # Аутентификация через сессии Django
#             URLRouter(
#                 chat.routing.websocket_urlpatterns
#             )
#         )
#     ),
# })
