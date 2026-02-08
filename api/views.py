import json
import uuid
import threading
from groq import Groq
from django.conf import settings
from django.db import models as django_models
from django.utils import timezone

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import StudyPost, StudySession, ConversationNote, UserProfile, UserMedia
from .serializers import (
    StudyPostSerializer, StudySessionSerializer,
    ConversationNoteSerializer, UserProfileSerializer, 
    RegisterSerializer, UserSerializer, UserMediaSerializer
)

client = Groq(api_key=settings.GROQ_API_KEY)

# --- THE BACKGROUND WORKER FUNCTION (REPLACES TASKS.PY) ---
def analyze_conversation_thread(session_id, messages):
    try:
        session = StudySession.objects.get(id=session_id)
        
        # Format conversation exactly like tasks.py
        conversation_text = "\n".join([
            f"{msg.get('userName', 'User')}: {msg.get('text', '')}"
            for msg in messages
        ])

        prompt = f"""Analyze this study conversation and extract key learning points.
        
        Conversation:
        {conversation_text}

        Return exactly a JSON object with:
        1. key_concepts (list)
        2. definitions (list of {{'term': '...', 'definition': '...'}})
        3. study_tips (list)
        4. resources (list)
        5. summary (string)
        """

        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile", 
            messages=[
                {"role": "system", "content": "You are a helpful assistant that outputs only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.5,
            max_tokens=2048,
        )
        
        analysis = json.loads(completion.choices[0].message.content)

        # Create the note using all fields from the original tasks.py
        ConversationNote.objects.create(
            session=session,
            content=analysis.get('summary', 'No summary provided'),
            key_concepts=analysis.get('key_concepts', []),
            definitions=analysis.get('definitions', []),
            study_tips=analysis.get('study_tips', []),
            resources_mentioned=analysis.get('resources', []), # Assumed field name
            message_count_analyzed=len(messages)
        )
        
        # Update session metadata
        session.last_ai_analysis = timezone.now()
        session.save()
        print(f"✅ Success: Note generated for Session {session_id}")
        
    except Exception as e:
        print(f"❌ Threading AI Error: {str(e)}")


# --- VIEWS ---

class RegisterView(APIView):
    permission_classes = []
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            UserProfile.objects.get_or_create(user=user)
            refresh = RefreshToken.for_user(user)
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserProfileViewSet(viewsets.ModelViewSet):
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    # 1. Allow looking up by username (matches your profileAPI.getProfile(username))
    lookup_field = 'user__username' 
    
    # 2. Allow any logged in user to VIEW profiles, but keep restrictions on editing
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Allow viewing ALL profiles so you can see others
        return UserProfile.objects.all()

    @action(detail=False, methods=['get', 'post'])
    def me(self, request):
        # This keeps your existing /me logic for the logged-in user
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        if request.method == 'POST':
            serializer = self.get_serializer(profile, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(profile).data)
    @action(detail=False, methods=['post'])
    def upload_media(self, request):
        file_url = request.data.get('fileUrl') or request.data.get('file_url')
        category = request.data.get('category')
        raw_text = request.data.get('aiAnalysisText', '').strip()
        is_public = request.data.get('is_public', True)
        if not file_url: return Response({"error": "No URL provided"}, status=400)

        media_obj = UserMedia.objects.create(
            user=request.user, file_url=file_url, category=category, is_public=is_public,
            title="Processing..." if category == 'certificate' else "New Note"
        )

        if category == 'certificate' and raw_text:
            try:
                completion = client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that outputs only JSON."},
                        {"role": "user", "content": f"Analyze: '{raw_text}'. Return JSON with 'title', 'issuer', 'skills' (list)."}
                    ],
                    response_format={"type": "json_object"}
                )
                ai_data = json.loads(completion.choices[0].message.content)
                media_obj.title = ai_data.get('title') or "Verified Certificate"
                media_obj.issuer = ai_data.get('issuer') or "Verified Issuer"
                media_obj.skills = ai_data.get('skills') or []
                media_obj.save()
            except:
                media_obj.title = "Certificate (AI Error)"; media_obj.save()
        
        return Response(UserMediaSerializer(media_obj).data, status=201)

class StudyPostViewSet(viewsets.ModelViewSet):
    queryset = StudyPost.objects.filter(is_active=True)
    serializer_class = StudyPostSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = StudyPost.objects.filter(is_active=True)
        subject = self.request.query_params.get('subject')
        if subject: queryset = queryset.filter(subject__icontains=subject)
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                django_models.Q(title__icontains=search) |
                django_models.Q(topic__icontains=search) |
                django_models.Q(description__icontains=search)
            )
        return queryset.order_by('-created_at')

    def perform_create(self, serializer): serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'])
    def join(self, request, pk=None):
        post = self.get_object()
        session = StudySession.objects.filter(post=post, is_active=True).first()
        if not session:
            session = StudySession.objects.create(
                post=post, creator=post.user, is_active=True,
                firestore_chat_id=f"session_{uuid.uuid4().hex}", ai_notes_enabled=True
            )
            session.participants.add(post.user)
        
        if not session.participants.filter(id=request.user.id).exists():
            if session.participants.count() >= 5: return Response({'error': 'Full'}, status=400)
            session.participants.add(request.user)
        return Response(StudySessionSerializer(session).data)

class StudySessionViewSet(viewsets.ModelViewSet):
    queryset = StudySession.objects.all()
    serializer_class = StudySessionSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(
            django_models.Q(creator=self.request.user) | 
            django_models.Q(participants=self.request.user)
        ).distinct().order_by('-started_at')
    
    @action(detail=True, methods=['post'])
    def end_session(self, request, pk=None):
        """Exposes the end_session logic to the API"""
        session = self.get_object()
        
        # Check if the person trying to end it is the creator
        if session.creator != request.user:
            return Response({"error": "Only the creator can end the session"}, status=403)
            
        session.is_active = False
        session.ended_at = timezone.now()
        session.save()
        
        return Response({
            "status": "session ended",
            "ended_at": session.ended_at
        }, status=200)
    @action(detail=True, methods=['post'])
    def generate_notes(self, request, pk=None):
            session = self.get_object()
            messages = request.data.get('messages', [])
            
            if not messages:
                return Response({'error': 'No messages provided'}, status=400)
            
            # 1. Start the thread
            thread = threading.Thread(
                target=analyze_conversation_thread, 
                args=(session.id, messages)
            )
            thread.start()

            # 2. IMMEDIATELY return a response so Django is happy
            return Response({
                'message': 'Background analysis started',
                'status': 'processing'
            }, status=status.HTTP_202_ACCEPTED)
    @action(detail=True, methods=['get'])
    def notes(self, request, pk=None):
        """Allows fetching notes via /api/sessions/{id}/notes/"""
        session = self.get_object()
        notes = ConversationNote.objects.filter(session=session)
        serializer = ConversationNoteSerializer(notes, many=True)
        return Response(serializer.data)
    
        return Response({'message': 'Background analysis started'}, status=status.HTTP_202_ACCEPTED)

class ConversationNoteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ConversationNote.objects.all()
    serializer_class = ConversationNoteSerializer
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        return self.queryset.filter(
            django_models.Q(session__creator=self.request.user) | 
            django_models.Q(session__participants=self.request.user)
        ).distinct().order_by('-created_at')
class ExamPrepView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Routes the POST request based on the URL path.
        Matches: /api/exam-prep/ AND /api/exam-prep/solve/
        """
        path = request.path.rstrip('/') # Clean trailing slashes
        
        if path.endswith('solve'):
            return self._solve_question(request)
        
        return self._generate_materials(request)

    def _generate_materials(self, request):
        """Internal method to generate study materials"""
        data = request.data
        subject = data.get('subject')
        topic = data.get('topic')
        grade = data.get('gradeLevel')
        difficulty = data.get('difficulty', 'Intermediate')

        if not all([subject, topic, grade]):
            return Response({"error": "Missing required fields: subject, topic, and gradeLevel"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        prompt = f"""
        Act as an expert tutor. Create a study guide for a {grade} student on {subject}: {topic}.
        Difficulty level: {difficulty}.
        
        Return ONLY a JSON object with:
        1. keyConcepts: (list of strings)
        2. questions: (list of objects with 'id' and 'text')
        """

        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are a teacher who only responds in JSON format."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.7
            )
            
            analysis = json.loads(completion.choices[0].message.content)
            return Response(analysis, status=200)

        except Exception as e:
            return Response({"error": f"Groq Generation Error: {str(e)}"}, 
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _solve_question(self, request):
        """Internal method to solve a specific question"""
        question_text = request.data.get('question')
        
        if not question_text:
            return Response({"error": "No question provided"}, 
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": "You are an expert tutor. Solve the following exam question clearly, accurately, and step-by-step."},
                    {"role": "user", "content": f"Please solve this question: {question_text}"}
                ],
                temperature=0.3 # Lower temperature for more factual/precise solving
            )
            return Response({"answer": completion.choices[0].message.content}, status=200)
        except Exception as e:
            return Response({"error": f"Groq Solver Error: {str(e)}"}, 
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)