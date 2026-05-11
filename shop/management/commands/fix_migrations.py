from django.core.management.base import BaseCommand
from django.db import connection
from django.core.management import call_command

class Command(BaseCommand):
    help = 'Fix social_django migration conflict by faking history'

    def handle(self, *args, **options):
        self.stdout.write("Starting robust fix for social_django migrations...")
        
        with connection.cursor() as cursor:
            # Step 1: Remove any existing records for social_django
            # This ensures we have a clean slate to fake from
            self.stdout.write("Deleting existing social_django migration records...")
            cursor.execute("DELETE FROM django_migrations WHERE app = 'social_django';")
            
        # Step 2: Use Django's built-in --fake flag
        # This automatically detects all migration files for the app and 
        # marks them as applied in django_migrations without running SQL.
        # This is much safer than hardcoding migration names.
        self.stdout.write("Marking all social_django migrations as applied (faking)...")
        try:
            call_command('migrate', 'social_django', fake=True)
            self.stdout.write(self.style.SUCCESS("Successfully faked social_django migrations!"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to fake migrations: {e}"))
            
        self.stdout.write("Migration fix complete.")