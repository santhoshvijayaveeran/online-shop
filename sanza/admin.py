from django.contrib import admin
from .models import Conversation, Message, MessageFeedback, SanzaAnalytics

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'user', 'language', 'is_escalated', 'created_at', 'message_count')
    list_filter = ('language', 'is_escalated', 'created_at')
    search_fields = ('session_id', 'escalation_email')
    readonly_fields = ('session_id', 'created_at')

    def message_count(self, obj):
        return obj.messages.count()
    message_count.short_description = 'Messages'

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'role', 'intent', 'tokens_used', 'response_time_ms', 'timestamp')
    list_filter = ('role', 'intent', 'timestamp')
    search_fields = ('content',)
    readonly_fields = ('timestamp',)

@admin.register(SanzaAnalytics)
class SanzaAnalyticsAdmin(admin.ModelAdmin):
    list_display = ('date', 'total_conversations', 'total_messages', 'avg_response_time_ms', 'escalations', 'satisfaction_score')
    readonly_fields = [f.name for f in SanzaAnalytics._meta.get_fields()]

@admin.register(MessageFeedback)
class MessageFeedbackAdmin(admin.ModelAdmin):
    list_display = ('message', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
