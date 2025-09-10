from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.models import College


def _format_time_field(t: Any) -> str:
    """Return a HH:MM:SS string for a time-like object or pass through a string."""
    if isinstance(t, str):
        return t
    try:
        return t.strftime('%H:%M:%S')
    except Exception:
        return str(t)


class CollegeAccessView(APIView):
    """
    Check if the current user can access the application based on their college's
    active status and time window settings.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        
        # Debug logging
        print(f"CollegeAccessView: User authenticated: {user.is_authenticated}")
        print(f"CollegeAccessView: User: {user}")
        print(f"CollegeAccessView: User type: {type(user)}")
        print(f"CollegeAccessView: Authorization header: {request.META.get('HTTP_AUTHORIZATION', 'MISSING')}")
        print(f"CollegeAccessView: Content-Type: {request.META.get('CONTENT_TYPE', 'MISSING')}")
        print(f"CollegeAccessView: HTTP_HOST: {request.META.get('HTTP_HOST', 'MISSING')}")
        if hasattr(user, 'college'):
            print(f"CollegeAccessView: User college: {user.college}")
        
        # Check if user has a college
        if not user.college:
            # Auto-assign college based on email domain
            from accounts.utils import get_domain_from_email

            domain = get_domain_from_email(user.email)

            # Try to find existing college for this domain
            college = College.objects.filter(domain=domain).first()

            # If no college exists, create one
            if not college:
                # Extract a readable college name from domain
                college_name = domain.replace(".", " ").title()
                if college_name.endswith(" Edu"):
                    college_name = college_name[:-4] + " University"
                elif college_name.endswith(" Ac In"):
                    college_name = college_name[:-6] + " College"
                elif domain.lower() in {"gmail.com", "googlemail.com"}:
                    college_name = "Gmail Users"

                college = College.objects.create(
                    name=college_name,
                    domain=domain,
                    window_start=datetime.strptime('20:00:00', '%H:%M:%S').time(),  # Default 8 PM
                    window_end=datetime.strptime('21:00:00', '%H:%M:%S').time(),  # Default 9 PM
                    is_active=False,  # New colleges start inactive
                )

            # Assign college to user
            user.college = college
            user.save()

        college = user.college

        # Debug college settings
        print(f"CollegeAccessView: College name: {college.name}")
        print(f"CollegeAccessView: College is_active: {college.is_active}")
        print(f"CollegeAccessView: College window_start: {college.window_start}")
        print(f"CollegeAccessView: College window_end: {college.window_end}")
        print(f"CollegeAccessView: Current time: {timezone.localtime().time()}")

        # Check if college is active
        if not college.is_active:
            return Response(
                {
                    "can_access": False,
                    "reason": "college_inactive",
                    "message": f"Access for {college.name} is currently disabled",
                    "college_name": college.name,
                    "college_domain": college.domain,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check time window using local time based on settings.TIME_ZONE
        current_time = timezone.localtime().time()

        # Handle time window that might cross midnight
        if college.window_start <= college.window_end:
            # Same day window (e.g., 20:00 to 21:00)
            in_time_window = college.window_start <= current_time <= college.window_end
        else:
            # Cross-midnight window (e.g., 23:00 to 01:00)
            in_time_window = current_time >= college.window_start or current_time <= college.window_end

        if not in_time_window:
            return Response(
                {
                    "can_access": False,
                    "reason": "outside_window",
                    "message": f'Access is only available between {college.window_start.strftime("%H:%M")} and {college.window_end.strftime("%H:%M")}',
                    "college_name": college.name,
                    "window_start": _format_time_field(college.window_start),
                    "window_end": _format_time_field(college.window_end),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # User can access
        return Response(
            {
                "can_access": True,
                "message": "Access granted",
                "college_name": college.name,
                "window_start": _format_time_field(college.window_start),
                "window_end": _format_time_field(college.window_end),
                "time_remaining_seconds": self._calculate_time_remaining(current_time, college.window_end),
            },
            status=status.HTTP_200_OK,
        )

    def _calculate_time_remaining(self, current_time, window_end):
        """Calculate seconds remaining in the current window"""
        try:
            # Convert times to datetime for calculation
            now_dt = datetime.combine(datetime.today(), current_time)
            end_dt = datetime.combine(datetime.today(), window_end)

            # Handle cross-midnight case robustly
            if window_end < current_time:
                end_dt = end_dt + timedelta(days=1)

            remaining = (end_dt - now_dt).total_seconds()
            return max(0, int(remaining))
        except:
            return 0


class CollegeStatusView(APIView):
    """
    Get college information for the current user including timing windows
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        if not user.college:
            # Auto-assign college based on email domain
            from accounts.utils import get_domain_from_email

            domain = get_domain_from_email(user.email)

            # Try to find existing college for this domain
            college = College.objects.filter(domain=domain).first()

            # If no college exists, create one
            if not college:
                # Extract a readable college name from domain
                college_name = domain.replace(".", " ").title()
                if college_name.endswith(" Edu"):
                    college_name = college_name[:-4] + " University"

                elif college_name.endswith(" Ac In"):
                    college_name = college_name[:-6] + " College"
                elif domain.lower() in {"gmail.com", "googlemail.com"}:
                    college_name = "Gmail Users"

                college = College.objects.create(
                    name=college_name,
                    domain=domain,
                    window_start=datetime.strptime('20:00:00', '%H:%M:%S').time(),  # Default 8 PM
                    window_end=datetime.strptime('21:00:00', '%H:%M:%S').time(),  # Default 9 PM
                    is_active=False,  # New colleges start inactive
                )

            # Assign college to user
            user.college = college
            user.save()

        college = user.college
        # Use local time based on settings.TIME_ZONE
        current_time = timezone.localtime().time()

        # Calculate if currently in window
        if college.window_start <= college.window_end:
            in_window = college.window_start <= current_time <= college.window_end
        else:
            in_window = current_time >= college.window_start or current_time <= college.window_end

        return Response(
            {
                "has_college": True,
                "college": {
                    "id": college.id,
                    "name": college.name,
                    "domain": college.domain,
                    "is_active": college.is_active,
                    "window_start": college.window_start.strftime("%H:%M:%S"),
                    "window_end": college.window_end.strftime("%H:%M:%S"),
                    "currently_in_window": in_window,
                    "can_access": college.is_active and in_window,
                },
            },
            status=status.HTTP_200_OK,
        )


# WebSocket and Chat Views

from rest_framework.decorators import api_view, permission_classes

from base.models import Chat, Message, WaitingListEntry
from base.services import MatchingService


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def queue_status(request):
    """Get current queue status for user's college."""
    user = request.user

    if not user.college:
        return Response({"error": "No college assigned to user"}, status=status.HTTP_400_BAD_REQUEST)

    waiting_count = MatchingService.get_waiting_count(user.college)
    is_in_queue = WaitingListEntry.objects.filter(user=user, college=user.college).exists()

    return Response({
        "waiting_count": waiting_count,
        "college": user.college.name,
        "college_id": user.college.id,
        "is_in_queue": is_in_queue,
    })


@api_view(["GET"])  # New endpoint
@permission_classes([IsAuthenticated])
def college_activity(request):
    """Return activity stats for the current user's college: active chats and waiting users."""
    user = request.user

    if not user.college:
        return Response({"error": "No college assigned to user"}, status=status.HTTP_400_BAD_REQUEST)

    college = user.college

    # Count active chats for this college
    active_chats_count = Chat.objects.filter(college=college, is_active=True).count()

    # Count users waiting
    waiting_count = MatchingService.get_waiting_count(college)

    return Response(
        {
            "college_id": college.id,
            "college": college.name,
            "active_chats": active_chats_count,
            "waiting_count": waiting_count,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def join_queue(request):
    """Add user to waiting queue."""
    user = request.user

    if not user.college:
        return Response({"error": "No college assigned to user"}, status=status.HTTP_400_BAD_REQUEST)

    # Check if user already has an active chat
    active_chat = MatchingService.get_active_chat(user)
    if active_chat:
        return Response(
            {"error": "User already has an active chat", "chat_id": str(active_chat.id)}, status=status.HTTP_400_BAD_REQUEST
        )

    added = MatchingService.add_to_waiting_list(user, user.college)

    if added:
        # Try to find an immediate match
        chat = MatchingService.try_match_users(user.college)

        if chat:
            return Response(
                {"matched": True, "chat_id": str(chat.id), "message": "Match found!"}, status=status.HTTP_201_CREATED
            )
        else:
            waiting_count = MatchingService.get_waiting_count(user.college)
            return Response(
                {
                    "matched": False,
                    "waiting_count": waiting_count,
                    "message": "Added to queue. Waiting for match...",
                    "is_in_queue": True,
                },
                status=status.HTTP_201_CREATED,
            )
    else:
        # If already in queue, don't treat as error; return current status
        waiting_count = MatchingService.get_waiting_count(user.college)
        return Response(
            {
                "matched": False,
                "waiting_count": waiting_count,
                "message": "Already in queue",
                "is_in_queue": True,
            },
            status=status.HTTP_200_OK,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def leave_queue(request):
    """Remove user from waiting queue."""
    user = request.user

    if not user.college:
        return Response({"error": "No college assigned to user"}, status=status.HTTP_400_BAD_REQUEST)

    removed = MatchingService.remove_from_waiting_list(user, user.college)

    if removed:
        return Response({"message": "Removed from queue successfully"})
    else:
        return Response({"error": "Not in queue"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_chat(request, chat_id):
    """Get chat details and recent messages."""
    user = request.user

    try:
        chat = Chat.objects.get(id=chat_id, is_active=True)

        if not chat.is_participant(user):
            return Response({"error": "Not authorized to access this chat"}, status=status.HTTP_403_FORBIDDEN)

        # Get recent messages
        messages = Message.objects.filter(chat=chat).order_by("-created_at")[:50]

        message_data = []
        for message in reversed(messages):
            message_data.append(
                {
                    "id": str(message.id),
                    "content": message.content,
                    "message_type": message.message_type,
                    "timestamp": message.created_at.isoformat(),
                    "is_own": message.sender == user if message.sender else False,
                }
            )

        return Response(
            {
                "chat_id": str(chat.id),
                "college": chat.college.name,
                "created_at": chat.created_at.isoformat(),
                "is_active": chat.is_active,
                "messages": message_data,
            }
        )

    except Chat.DoesNotExist:
        return Response({"error": "Chat not found or inactive"}, status=status.HTTP_404_NOT_FOUND)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_active_chat(request):
    """Get user's current active chat if any."""
    user = request.user

    active_chat = MatchingService.get_active_chat(user)

    if active_chat:
        return Response(
            {
                "has_active_chat": True,
                "chat_id": str(active_chat.id),
                "college": active_chat.college.name,
                "created_at": active_chat.created_at.isoformat(),
            }
        )
    else:
        return Response({"has_active_chat": False})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def end_chat(request, chat_id):
    """End an active chat."""
    user = request.user

    try:
        chat = Chat.objects.get(id=chat_id, is_active=True)

        if not chat.is_participant(user):
            return Response({"error": "Not authorized to end this chat"}, status=status.HTTP_403_FORBIDDEN)

        success = MatchingService.end_chat(chat)

        if success:
            return Response({"message": "Chat ended successfully"})
        else:
            return Response({"error": "Chat is already ended"}, status=status.HTTP_400_BAD_REQUEST)

    except Chat.DoesNotExist:
        return Response({"error": "Chat not found"}, status=status.HTTP_404_NOT_FOUND)
