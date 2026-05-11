from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # social_django migration records delete பண்ணு
            cursor.execute("DELETE FROM django_migrations WHERE app = 'social_django';")
            
            # social_django migrations fake-ஆ mark பண்ணு (tables already exist)
            cursor.execute("""
                INSERT INTO django_migrations (app, name, applied)
                SELECT 'social_django', name, NOW()
                FROM (VALUES
                    ('0001_initial'),
                    ('0002_add_related_name'),
                    ('0003_alter_email_max_length'),
                    ('0004_auto_20160423_0400'),
                    ('0005_auto_20160727_2333'),
                    ('0006_partial'),
                    ('0007_code_timestamp'),
                    ('0008_partial_timestamp'),
                    ('0009_auto_20191128_0112'),
                    ('0010_uid_db_index'),
                    ('0011_alter_id_fields'),
                    ('0012_usersocialauth_extra_data_new'),
                    ('0013_migrate_extra_data'),
                    ('0014_remove_old_extra_data'),
                    ('0015_auto_20230605_0711')
                ) AS t(name)
                ON CONFLICT DO NOTHING;
            """)
        
        self.stdout.write("social_django migrations fixed!")