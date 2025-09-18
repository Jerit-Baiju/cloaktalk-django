from django.core.management.base import BaseCommand

from base.models import Chat


class Command(BaseCommand):
    help = "Deactivate all chats by setting is_active=False"

    def handle(self, *_args, **_options):
        qs = Chat.objects.filter(is_active=True)
        count = qs.update(is_active=False)
        self.stdout.write(self.style.SUCCESS(f"Deactivated {count} chat(s)."))
