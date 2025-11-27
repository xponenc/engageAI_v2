from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def send_activation_email(self, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    activation_link = self.request.build_absolute_uri(
        reverse_lazy("users:activate", kwargs={"uidb64": uid, "token": token})
    )

    html_content = render_to_string("emails/activation_email.html", {
        "activation_link": activation_link
    })

    msg = EmailMultiAlternatives(
        subject="Подтверждение email",
        body="Чтобы подтвердить email, откройте письмо в HTML-формате.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send()
