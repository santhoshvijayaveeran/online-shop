from django.core.management.base import BaseCommand
from sanza.data.indexer import build_index

class Command(BaseCommand):
    help = 'Rebuild Sanza FAISS vector index'

    def handle(self, *args, **kwargs):
        self.stdout.write('Rebuilding Sanza index...')
        build_index()
        self.stdout.write(self.style.SUCCESS('Sanza index rebuild complete!'))
