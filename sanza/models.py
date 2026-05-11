import uuid
from django.db import models
from django.contrib.auth.models import User

class Conversation(models.Model):
    session_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    language = models.CharField(max_length=10, default='en')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_escalated = models.BooleanField(default=False)
    escalation_name = models.CharField(max_length=255, null=True, blank=True)
    escalation_email = models.EmailField(null=True, blank=True)
    metadata = models.JSONField(default=dict)

    def __str__(self):
        return f"Conversation {self.session_id}"

class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20) # 'user' | 'assistant' | 'system'
    content = models.TextField()
    intent = models.CharField(max_length=100, null=True, blank=True)
    retrieved_context = models.JSONField(default=list)
    tokens_used = models.IntegerField(default=0)
    response_time_ms = models.IntegerField(default=0)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.role}: {self.content[:50]}"

class MessageFeedback(models.Model):
    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name='feedback')
    rating = models.CharField(max_length=10) # 'up' | 'down'
    created_at = models.DateTimeField(auto_now_add=True)

class SanzaAnalytics(models.Model):
    date = models.DateField(auto_now_add=True)
    total_conversations = models.IntegerField(default=0)
    total_messages = models.IntegerField(default=0)
    avg_response_time_ms = models.FloatField(default=0.0)
    escalations = models.IntegerField(default=0)
    top_intents = models.JSONField(default=dict)
    satisfaction_score = models.FloatField(default=0.0)

    class Meta:
        verbose_name_plural = "Sanza Analytics"
