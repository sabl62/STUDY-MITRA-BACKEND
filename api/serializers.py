from rest_framework import serializers
from django.contrib.auth.models import User
from .models import StudyPost, StudySession, ConversationNote, UserProfile, UserMedia

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'first_name', 'last_name']

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        UserProfile.objects.create(user=user)
        return user

class UserMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserMedia
        fields = '__all__'

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    # 1. Change to SerializerMethodField
    portfolio_media = serializers.SerializerMethodField()
    
    class Meta:
        model = UserProfile
        fields = ['id', 'user', 'bio', 'profile_picture', 'study_interests', 'created_at', 'portfolio_media']

    # 2. Add the privacy filter logic
    def get_portfolio_media(self, obj):
        request = self.context.get('request')
        # Start with all media for this profile's user
        queryset = UserMedia.objects.filter(user=obj.user)

        # PRIVACY GATEKEEPER:
        # If the requester is NOT the owner of this profile
        if request and request.user != obj.user:
            # ONLY return notes marked as public
            queryset = queryset.filter(is_public=True)
            
        return UserMediaSerializer(queryset, many=True).data
class StudyPostSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    active_sessions_count = serializers.SerializerMethodField()
    class Meta:
        model = StudyPost
        fields = '__all__'

    def get_active_sessions_count(self, obj):
        return obj.sessions.filter(is_active=True).count()

class StudySessionSerializer(serializers.ModelSerializer):
    post = StudyPostSerializer(read_only=True)
    creator = UserSerializer(read_only=True)
    participants = UserSerializer(many=True, read_only=True)
    class Meta:
        model = StudySession
        fields = '__all__'

class ConversationNoteSerializer(serializers.ModelSerializer):
    session_info = serializers.SerializerMethodField()
    class Meta:
        model = ConversationNote
        fields = '__all__'

    def get_session_info(self, obj):
        return {'id': obj.session.id, 'topic': obj.session.post.topic}