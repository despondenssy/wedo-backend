from django.db import models


class File(models.Model):
    storage_key = models.CharField(max_length=500)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    size = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'files'

    def __str__(self):
        return self.original_name
