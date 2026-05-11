from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Step 1: Migration records delete பண்ணு
            cursor.execute("DELETE FROM django_migrations WHERE app = 'social_django';")
            
            # Step 2: எல்லா migrations-யும் fake ஆ insert பண்ணு
            cursor.execute("""
                INSERT INTO django_migrations (app, name, applied)
                VALUES
                    ('social_django', '0001_initial', NOW()),
                    ('social_django', '0002_add_related_name', NOW()),
                    ('social_django', '0003_alter_email_max_length', NOW()),
                    ('social_django', '0004_auto_20160423_0400', NOW()),
                    ('social_django', '0005_auto_20160727_2333', NOW()),
                    ('social_django', '0006_partial', NOW()),
                    ('social_django', '0007_code_timestamp', NOW()),
                    ('social_django', '0008_partial_timestamp', NOW()),
                    ('social_django', '0009_auto_20191118_0520', NOW()),
                    ('social_django', '0010_uid_db_index', NOW()),
                    ('social_django', '0011_alter_id_fields', NOW()),
                    ('social_django', '0012_usersocialauth_extra_data_new', NOW()),
                    ('social_django', '0013_migrate_extra_data', NOW()),
                    ('social_django', '0014_remove_old_extra_data', NOW()),
                    ('social_django', '0015_auto_20230605_0711', NOW())
                ON CONFLICT DO NOTHING;
            """)

        self.stdout.write("social_django migrations fixed!")