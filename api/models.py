from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class StudyPost(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='study_posts')
    title = models.CharField(max_length=200)
    topic = models.CharField(max_length=200)
    description = models.TextField()
    subject = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} by {self.user.username}"

class StudySession(models.Model):
    post = models.ForeignKey(StudyPost, on_delete=models.CASCADE, related_name='sessions')
    creator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_sessions')
    participants = models.ManyToManyField(User, related_name='joined_sessions', blank=True)
    firestore_chat_id = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ai_notes_enabled = models.BooleanField(default=True)
    last_ai_analysis = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Session {self.id} - {self.post.title}" # Fixed reference

    def end_session(self):
        self.is_active = False
        self.ended_at = timezone.now()
        self.save()

class ConversationNote(models.Model):
    session = models.ForeignKey(StudySession, on_delete=models.CASCADE, related_name='ai_notes')
    content = models.TextField()
    key_concepts = models.JSONField(default=list)
    definitions = models.JSONField(default=list)
    study_tips = models.JSONField(default=list)
    resources_mentioned = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    message_count_analyzed = models.IntegerField(default=0)
    is_synced_offline = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.TextField(blank=True)
    profile_picture = models.ImageField(upload_to='profiles/', null=True, blank=True)
    study_interests = models.JSONField(default=list)  
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Profile of {self.user.username}"

class UserMedia(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolio_media') # <--- MUST MATCH SERIALIZER
    file_url = models.URLField()
    category = models.CharField(max_length=20) # 'note' or 'certificate'
    title = models.CharField(max_length=255, blank=True, null=True)
    issuer = models.CharField(max_length=255, blank=True, null=True)
    skills = models.JSONField(default=list, blank=True, null=True)
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']