from django.core.management.base import BaseCommand
from django.db import connection
from django.core.management import call_command

class Command(BaseCommand):
    help = 'Fix social_django migration conflict'

    def handle(self, *args, **kwargs):
        self.stdout.write('Starting migration fix for social_django...')
        with connection.cursor() as cursor:
            try:
                # Check if django_migrations table exists first
                cursor.execute("SELECT 1 FROM django_migrations LIMIT 1")
                cursor.execute("""
                    DELETE FROM django_migrations 
                    WHERE app = 'social_django'
                """)
                self.stdout.write(self.style.SUCCESS('Deleted social_django migration records from django_migrations table'))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'Note: Could not delete social_django records (table might not exist yet): {e}'))

        try:
            self.stdout.write('Running: python manage.py migrate social_django')
            call_command('migrate', 'social_django')
            self.stdout.write(self.style.SUCCESS('social_django migration successful'))
        except Exception as e:
             self.stdout.write(self.style.ERROR(f'social_django specific migration failed: {e}'))
