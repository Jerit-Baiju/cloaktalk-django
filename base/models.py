import uuid

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
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE)
    college = models.ForeignKey(College, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["user", "college"]

    def __str__(self):
        return f"{self.college.name} - {self.user.email}"


class Chat(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college = models.ForeignKey(College, on_delete=models.CASCADE)
    participant1 = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="chats_as_participant1")
    participant2 = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="chats_as_participant2")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "chats"

    def __str__(self):
        return f"{self.college.name}: {self.participant1.first_name} -> {self.participant2.first_name}"

    def get_participants(self):
        return [self.participant1, self.participant2]

    def is_participant(self, user):
        return user in [self.participant1, self.participant2]


class Message(models.Model):
    MESSAGE_TYPES = [
        ("text", "Text"),
        ("system", "System"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey("accounts.User", on_delete=models.CASCADE, null=True, blank=True)
    content = models.TextField()
    message_type = models.CharField(max_length=10, choices=MESSAGE_TYPES, default="text")
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        db_table = "messages"
        ordering = ["created_at"]

    def __str__(self):
        sender_name = self.sender.first_name if self.sender else "System"
        return f"{sender_name} -> {self.content}"


class Feedback(models.Model):
    comments = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "feedbacks"

    def __str__(self):
        return f"Feedback - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class Confession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content = models.TextField()
    author = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="confessions")
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="confessions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Many-to-many fields for likes and dislikes
    liked_by = models.ManyToManyField("accounts.User", related_name="liked_confessions", blank=True)
    disliked_by = models.ManyToManyField("accounts.User", related_name="disliked_confessions", blank=True)

    class Meta:
        db_table = "confessions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Confession by {self.author.email} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
    
    @property
    def likes_count(self):
        return self.liked_by.count()
    
    @property
    def dislikes_count(self):
        return self.disliked_by.count()
