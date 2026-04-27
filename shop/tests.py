from django.test import TestCase
from .models import Category

class CategoryTest(TestCase):

    def test_create_category(self):
        category = Category.objects.create(name="Electronics")
        self.assertEqual(category.name, "Electronics")