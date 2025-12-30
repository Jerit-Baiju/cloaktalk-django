import asyncio
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from jwt import decode as jwt_decode
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken

from base.models import Chat, Message, WaitingListEntry
from base.services import MatchingService

logger = logging.getLogger(__name__)
User = get_user_model()


class QueueConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for handling waiting queue functionality."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Predefine attributes to satisfy linters
        self.user = None
        self.college_group_name = ""
        self.user_group_name = ""

    async def connect(self):
        """Handle WebSocket connection."""
        # Try to authenticate user from token
        self.user = await self.get_user_from_token()

        if not self.user or isinstance(self.user, AnonymousUser):
            await self.close(code=4001)
            return

        # Check if user has college (using sync_to_async for foreign key access)
        # Service accounts don't need a college
        user_college = await database_sync_to_async(lambda: self.user.college)()
        is_service_account = await database_sync_to_async(lambda: self.user.is_service_account)()

        if not user_college and not is_service_account:
            await self.close(code=4002)  # No college assigned
            return

        # Join college group for queue updates (or global group for service accounts)
        if user_college:
            self.college_group_name = f"queue_{user_college.id}"
        else:
            self.college_group_name = "queue_service_accounts"

        await self.channel_layer.group_add(self.college_group_name, self.channel_name)

        # Also join user-specific group for direct messages
        self.user_group_name = f"user_{self.user.id}"
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)

        await self.accept()

        # Send initial queue status
        await self.send_queue_status()

        # Broadcast user presence update
        await self.channel_layer.group_send(
            self.college_group_name, {"type": "user_presence_update", "user_id": str(
                self.user.id), "status": "online"}
        )

    async def get_user_from_token(self):
        """Extract and validate JWT token from query parameters."""
        try:
            # Get token from query string
            query_string = self.scope.get("query_string", b"").decode()
            query_params = dict(param.split("=")
                                for param in query_string.split("&") if "=" in param)
            token = query_params.get("token")

            if not token:
                return None

            # Validate JWT token
            try:
                UntypedToken(token)
            except (InvalidToken, TokenError):
                return None

            # Decode token to get user ID
            decoded_token = jwt_decode(
                token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = decoded_token.get("user_id")

            if not user_id:
                return None

            # Get user from database
            user = await database_sync_to_async(User.objects.get)(id=user_id)
            return user
        except Exception as e:
            logger.error("Error authenticating WebSocket user: %s", e)
            return None

    async def disconnect(self, code):
        """Handle WebSocket disconnection."""
        if hasattr(self, "college_group_name"):
            await self.channel_layer.group_discard(self.college_group_name, self.channel_name)

            # Broadcast user presence update
            await self.channel_layer.group_send(
                self.college_group_name,
                {"type": "user_presence_update", "user_id": str(
                    self.user.id) if self.user else None, "status": "offline"},
            )

        if hasattr(self, "user_group_name"):
            await self.channel_layer.group_discard(self.user_group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data or "{}")
            action = data.get("action")

            if action == "join_queue":
                await self.join_queue()
            elif action == "leave_queue":
                await self.leave_queue()
            elif action == "check_status":
                await self.send_queue_status()
            elif action == "heartbeat":
                await self.send(text_data=json.dumps({"type": "pong"}))

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"error": "Invalid JSON format"}))

    async def join_queue(self):
        """Add user to waiting queue."""
        user_college = await database_sync_to_async(lambda: self.user.college)()
        is_service_account = await database_sync_to_async(lambda: self.user.is_service_account)()

        # If user already has an active chat, return a non-queue status
        active_chat = await database_sync_to_async(MatchingService.get_active_chat)(self.user)
        if active_chat:
            await self.send(
                text_data=json.dumps(
                    {"type": "chat_matched", "chat_id": str(
                        active_chat.id), "message": "Already in an active chat."}
                )
            )
            return
        added = await database_sync_to_async(MatchingService.add_to_waiting_list)(self.user, user_college)

        if added:
            # Notify college group about queue update
            await self.channel_layer.group_send(self.college_group_name, {"type": "queue_update", "action": "user_joined"})

            # Get queue statistics for user feedback
            # For service accounts, check all colleges for matches
            if is_service_account:
                queue_stats = {"total_waiting": 1,
                               "message": "Looking for users to chat with..."}
                college_name = "Service Account"
            else:
                queue_stats = await database_sync_to_async(MatchingService.get_queue_waiting_stats)(user_college)
                college_name = user_college.name

            # Send enhanced queue status with matching info
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "queue_status",
                        "waiting_count": queue_stats.get("total_waiting", 1),
                        "college": college_name,
                        "is_in_queue": True,
                        "queue_stats": queue_stats,
                        "message": queue_stats.get("message") or self._get_queue_message(queue_stats),
                    }
                )
            )

            # Try to find a match
            await self.try_match()

            # Also trigger matching for the group (helps match users already waiting)
            await self.channel_layer.group_send(
                self.college_group_name,
                {"type": "trigger_match"}
            )
        else:
            # Already in queue; respond gracefully with current status
            count = await database_sync_to_async(MatchingService.get_waiting_count)(user_college)
            await self.send(
                text_data=json.dumps(
                    {"type": "queue_status", "waiting_count": count,
                        "college": user_college.name, "is_in_queue": True}
                )
            )

    def _get_queue_message(self, queue_stats):
        """Generate user-friendly message based on queue statistics."""
        if queue_stats["fresh_users"] >= 2:
            return "Great! You'll be matched with someone new very soon."
        elif queue_stats["fresh_users"] >= 1:
            return "You'll be matched with someone who's new to the platform soon!"
        elif queue_stats["ready_for_matching"]:
            return "Looking for someone you haven't chatted with before..."
        elif queue_stats["total_waiting"] >= 2:
            return "Finding the best match for you... This might take up to 5 seconds."
        else:
            return "Waiting for more users to join the queue..."

    async def leave_queue(self):
        """Remove user from waiting queue."""
        user_college = await database_sync_to_async(lambda: self.user.college)()
        removed = await database_sync_to_async(MatchingService.remove_from_waiting_list)(self.user, user_college)

        if removed:
            await self.channel_layer.group_send(self.college_group_name, {"type": "queue_update", "action": "user_left"})

    async def try_match(self):
        """Try to match users and create chat if possible."""
        user_college = await database_sync_to_async(lambda: self.user.college)()
        is_service_account = await database_sync_to_async(lambda: self.user.is_service_account)()

        # Service accounts can match across organizations, so try all colleges
        # Regular users try their own college with service accounts included
        if is_service_account:
            # Service account trying to match - check all colleges
            chat = await database_sync_to_async(MatchingService.try_match_service_account)()
        else:
            # Regular user trying to match - check their college with service accounts
            chat = await database_sync_to_async(MatchingService.try_match_users)(user_college, include_service_accounts=True)

        if chat:
            # Notify both participants about the match
            participants = await database_sync_to_async(chat.get_participants)()
            for participant in participants:
                await self.channel_layer.group_send(
                    f"user_{participant.id}", {
                        "type": "chat_matched", "chat_id": str(chat.id)}
                )

            # Update queue for college group
            await self.channel_layer.group_send(self.college_group_name, {"type": "queue_update", "action": "match_created"})
        else:
            # No immediate match found, schedule a retry after 5 seconds for potential matches
            await self.schedule_delayed_match(user_college)

    async def schedule_delayed_match(self, college):
        """Schedule a delayed match attempt for users who might be ready after waiting 5 seconds."""

        async def delayed_match():
            # Wait 6 seconds to ensure 5+ second wait time has passed
            await asyncio.sleep(6)

            # Try matching again - this time users who have waited 5+ seconds should be eligible
            # Include service accounts in matching
            chat = await database_sync_to_async(MatchingService.try_match_users)(college, include_service_accounts=True)

            if chat:
                # Notify both participants about the match
                participants = await database_sync_to_async(chat.get_participants)()
                for participant in participants:
                    await self.channel_layer.group_send(
                        f"user_{participant.id}", {
                            "type": "chat_matched", "chat_id": str(chat.id)}
                    )

                # Update queue for college group
                await self.channel_layer.group_send(
                    f"college_{college.id}", {
                        "type": "queue_update", "action": "match_created"}
                )

        # Create the delayed task
        asyncio.create_task(delayed_match())

    async def send_queue_status(self):
        """Send current queue status to user."""
        user_college = await database_sync_to_async(lambda: self.user.college)()
        is_service_account = await database_sync_to_async(lambda: self.user.is_service_account)()

        # Get enhanced queue statistics
        if user_college:
            queue_stats = await database_sync_to_async(MatchingService.get_queue_waiting_stats)(user_college)
            college_name = user_college.name
        else:
            # Service account without college
            queue_stats = {
                "total_waiting": 0,
                "fresh_users": 0,
                "experienced_users": 0,
                "ready_for_matching": True,
                "users_waiting_over_5_seconds": 0,
            }
            college_name = "Cross-Organization"

        # Determine if current user is already queued

        is_in_queue = await database_sync_to_async(
            WaitingListEntry.objects.filter(user=self.user).exists
        )()

        await self.send(
            text_data=json.dumps(
                {
                    "type": "queue_status",
                    "waiting_count": queue_stats["total_waiting"],
                    "college": college_name,
                    "is_in_queue": is_in_queue,
                    "queue_stats": queue_stats,
                    "is_service_account": is_service_account,
                    "message": self._get_queue_message(queue_stats) if is_in_queue else "Join the queue to start chatting!",
                }
            )
        )

    async def queue_update(self, _event):
        """Handle queue update events."""
        await self.send_queue_status()

    async def chat_matched(self, event):
        """Handle chat match notification."""
        await self.send(
            text_data=json.dumps(
                {"type": "chat_matched",
                    "chat_id": event["chat_id"], "message": "Match found! Redirecting to chat..."}
            )
        )

    async def user_presence_update(self, event):
        """Handle user presence updates."""
        # Only send presence updates to other users (not the user themselves)
        if event.get("user_id") != str(self.user.id):
            await self.send(
                text_data=json.dumps(
                    {"type": "user_presence_update",
                        "user_id": event["user_id"], "status": event["status"]}
                )
            )


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for handling chat functionality."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.chat_id = None
        self.chat = None
        self.room_group_name = ""

    async def connect(self):
        """Handle WebSocket connection for chat."""
        self.user = await self.get_user_from_token()
        self.chat_id = self.scope["url_route"]["kwargs"]["chat_id"]

        if not self.user or isinstance(self.user, AnonymousUser):
            await self.close(code=4001)
            return

        # Verify user is participant in this chat
        try:
            self.chat = await database_sync_to_async(Chat.objects.get)(id=self.chat_id, is_active=True)

            if not await database_sync_to_async(self.chat.is_participant)(self.user):
                await self.close(code=4003)  # Not authorized for this chat
                return

        except Chat.DoesNotExist:
            await self.close(code=4004)  # Chat not found
            return

        # Join chat room group
        self.room_group_name = f"chat_{self.chat_id}"
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)

        await self.accept()

        # Messages are already sent via the API call when the frontend connects
        # No need to send them again here to avoid duplication

    async def get_user_from_token(self):
        """Extract and validate JWT token from query parameters."""
        try:
            # Get token from query string
            query_string = self.scope.get("query_string", b"").decode()
            query_params = dict(param.split("=")
                                for param in query_string.split("&") if "=" in param)
            token = query_params.get("token")

            if not token:
                return None

            # Validate JWT token
            try:
                UntypedToken(token)
            except (InvalidToken, TokenError):
                return None

            # Decode token to get user ID
            decoded_token = jwt_decode(
                token, settings.SECRET_KEY, algorithms=["HS256"])
            user_id = decoded_token.get("user_id")

            if not user_id:
                return None

            # Get user from database
            user = await database_sync_to_async(User.objects.get)(id=user_id)
            return user
        except Exception as e:
            logger.error("Error authenticating WebSocket user: %s", e)
            return None

    async def disconnect(self, code):
        """Handle WebSocket disconnection."""
        if hasattr(self, "room_group_name"):
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Handle incoming chat messages."""
        try:
            data = json.loads(text_data or "{}")
            action = data.get("action")

            if action == "send_message":
                content = data.get("content", "").strip()
                if content:
                    await self.save_and_send_message(content)
            elif action == "end_chat":
                await self.end_chat()
            elif action == "typing_start":
                await self.broadcast_typing(True)
            elif action == "typing_stop":
                await self.broadcast_typing(False)
            elif action == "heartbeat":
                await self.send(text_data=json.dumps({"type": "pong"}))

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"error": "Invalid JSON format"}))

    async def save_and_send_message(self, content):
        """Save message to database and broadcast to chat room."""
        message = await database_sync_to_async(Message.objects.create)(
            chat=self.chat, sender=self.user, content=content, message_type="text"
        )

        # Broadcast message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "message_id": str(message.id),
                "content": content,
                "sender_id": str(self.user.id),
                "timestamp": message.created_at.isoformat(),
                "is_own": False,  # Will be set to True for sender
            },
        )

    async def end_chat(self):
        """End the current chat."""
        success = await database_sync_to_async(MatchingService.end_chat)(self.chat)

        if success:
            # Notify all participants that chat has ended
            await self.channel_layer.group_send(
                self.room_group_name, {
                    "type": "chat_ended", "message": "Chat has been ended"}
            )

    async def broadcast_typing(self, is_typing):
        """Broadcast typing indicator to other participants."""
        event_type = "typing_start" if is_typing else "typing_stop"
        await self.channel_layer.group_send(self.room_group_name, {"type": event_type, "user_id": str(self.user.id)})

    async def chat_message(self, event):
        """Handle chat message events."""
        is_own = event["sender_id"] == str(self.user.id)

        await self.send(
            text_data=json.dumps(
                {
                    "type": "message",
                    "message_id": event["message_id"],
                    "content": event["content"],
                    "sender_id": event["sender_id"],
                    "timestamp": event["timestamp"],
                    "is_own": is_own,
                    "message_type": "text",
                }
            )
        )

    async def chat_ended(self, event):
        """Handle chat ended events."""
        await self.send(text_data=json.dumps({"type": "chat_ended", "message": event["message"]}))

    async def typing_start(self, event):
        """Handle typing start events."""
        # Only send to other users, not the one who started typing
        if event["user_id"] != str(self.user.id):
            await self.send(text_data=json.dumps({"type": "typing_start", "user_id": event["user_id"]}))

    async def trigger_match(self, _event):
        """Handle trigger to attempt matching for users in the group."""
        # This is called when someone joins the queue to trigger matching for all waiting users
        user_college = await database_sync_to_async(lambda: self.user.college)()
        is_service_account = await database_sync_to_async(lambda: self.user.is_service_account)()

        # Check if this user is in the waiting list
        is_waiting = await database_sync_to_async(
            lambda: WaitingListEntry.objects.filter(user=self.user).exists()
        )()

        if is_waiting:
            # Try to match
            if is_service_account:
                chat = await database_sync_to_async(MatchingService.try_match_service_account)()
            else:
                chat = await database_sync_to_async(MatchingService.try_match_users)(user_college, include_service_accounts=True)

            if chat:
                # Notify both participants about the match
                participants = await database_sync_to_async(chat.get_participants)()
                for participant in participants:
                    await self.channel_layer.group_send(
                        f"user_{participant.id}", {
                            "type": "chat_matched", "chat_id": str(chat.id)}
                    )

    async def typing_stop(self, event):
        """Handle typing stop events."""
        # Only send to other users, not the one who stopped typing
        if event["user_id"] != str(self.user.id):
            await self.send(text_data=json.dumps({"type": "typing_stop", "user_id": event["user_id"]}))
