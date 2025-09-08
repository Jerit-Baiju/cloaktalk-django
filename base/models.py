from django.db import models

# Create your models here.


class College(models.Model):
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, unique=True)
    window_start = models.TimeField()
    window_end = models.TimeField()

    def __str__(self):
        return f"{self.name}"
