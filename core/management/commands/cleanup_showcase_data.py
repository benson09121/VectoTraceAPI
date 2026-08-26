from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from users.models import User

class Command(BaseCommand):
    help = 'Deletes demo users older than 24 hours to prevent database bloat.'

    def handle(self, *args, **kwargs):
        cutoff = timezone.now() - timedelta(hours=24)
        old_demo_users = User.objects.filter(is_demo_account=True, created_at__lt=cutoff)
        
        count = old_demo_users.count()
        if count > 0:
            # Django's ON DELETE CASCADE will handle deleting their organizations and monitors
            old_demo_users.delete()
            self.stdout.write(self.style.SUCCESS(f'Successfully deleted {count} old demo accounts.'))
        else:
            self.stdout.write(self.style.SUCCESS('No old demo accounts found to clean up.'))
