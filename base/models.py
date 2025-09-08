from django.db import models

# Create your models here.


class College(models.Model):
    name = models.CharField(max_length=255)
    domain = models.CharField(max_length=255, unique=True)
    window_start = models.TimeField()
    window_end = models.TimeField()
    is_active = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name}"


class WaitingListEntry(models.Model):
    email = models.EmailField(unique=True)
    college = models.ForeignKey(College, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.college.name} - {self.email}"
