import asyncio
import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from jwt import decode as jwt_decode
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import UntypedToken

from accounts.models import User
from base.models import Chat, Message, WaitingListEntry
from base.services import MatchingService

logger = logging.getLogger(__name__)
User = get_user_model()


class MainConsumer(AsyncWebsocketConsumer):
    """
    Unified WebSocket consumer handling all real-time communication.
    One connection per authenticated user for:
    - Queue management (join/leave/status)
    - Chat functionality (messages/typing/end)
    - User state updates (access, activity, presence)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = None
        self.user_group_name = ""
        self.college_group_name = ""
        self.chat_group_name = ""
        self.current_chat = None

    async def connect(self):
        """Handle WebSocket connection."""
        self.user = await self.get_user_from_token()

        if not self.user or isinstance(self.user, AnonymousUser):
            await self.close(code=4001)  # Unauthorized
            return

        # Get user's college
        user_college = await database_sync_to_async(lambda: self.user.college)()
        is_service_account = await database_sync_to_async(lambda: self.user.is_service_account)()

        if not user_college and not is_service_account:
            await self.close(code=4002)  # No college assigned
            return

        # Join user-specific group (for direct messages like chat_matched)
        self.user_group_name = f"user_{self.user.id}"
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)

        # Join college group for queue updates
        if user_college:
            self.college_group_name = f"college_{user_college.id}"
        else:
            self.college_group_name = "college_service_accounts"
        await self.channel_layer.group_add(self.college_group_name, self.channel_name)

        await self.accept()

        # Send initial state to user
        await self.send_initial_state()

    async def get_user_from_token(self):
        """Extract and validate JWT token from query parameters."""
        try:
            query_string = self.scope.get("query_string", b"").decode()
            query_params = dict(
                param.split("=") for param in query_string.split("&") if "=" in param
            )
            token = query_params.get("token")

            if not token:
                return None

            try:
                UntypedToken(token)
            except (InvalidToken, TokenError):
                return None

            decoded_token = jwt_decode(
                token, settings.SECRET_KEY, algorithms=["HS256"]
            )
            user_id = decoded_token.get("user_id")

            if not user_id:
                return None

            user = await database_sync_to_async(User.objects.get)(id=user_id)
            return user
        except Exception as e:
            logger.error("Error authenticating WebSocket user: %s", e)
            return None

    async def disconnect(self, code):
        """Handle WebSocket disconnection."""
        # Leave all groups
        if self.user_group_name:
            await self.channel_layer.group_discard(self.user_group_name, self.channel_name)

        if self.college_group_name:
            await self.channel_layer.group_discard(self.college_group_name, self.channel_name)
            # Broadcast offline status
            if self.user:
                await self.channel_layer.group_send(
                    self.college_group_name,
                    {"type": "presence_update", "user_id": str(self.user.id), "status": "offline"},
                )

        if self.chat_group_name:
            await self.channel_layer.group_discard(self.chat_group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data or "{}")
            action = data.get("action")

            # Queue actions
            if action == "join_queue":
                await self.join_queue()
            elif action == "leave_queue":
                await self.leave_queue()

            # Chat actions
            elif action == "join_chat":
                chat_id = data.get("chat_id")
                if chat_id:
                    await self.join_chat(chat_id)
            elif action == "leave_chat":
                await self.leave_chat()
            elif action == "send_message":
                content = data.get("content", "").strip()
                if content:
                    await self.send_chat_message(content)
            elif action == "end_chat":
                await self.end_chat()
            elif action == "typing_start":
                await self.broadcast_typing(True)
            elif action == "typing_stop":
                await self.broadcast_typing(False)

            # Utility actions
            elif action == "heartbeat":
                await self.send(text_data=json.dumps({"type": "pong"}))
            elif action == "refresh":
                await self.send_initial_state()

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({"type": "error", "message": "Invalid JSON format"}))

    # ==================== Initial State ====================

    async def send_initial_state(self):
        """Send complete initial state to user on connect/refresh."""
        user_college = await database_sync_to_async(lambda: self.user.college)()
        is_service_account = await database_sync_to_async(lambda: self.user.is_service_account)()

        # Check if user has an active chat
        active_chat = await database_sync_to_async(MatchingService.get_active_chat)(self.user)

        # Check if user is in queue
        is_in_queue = await database_sync_to_async(
            WaitingListEntry.objects.filter(user=self.user).exists
        )()

        # Get access data
        access_data = await self.get_access_data(user_college, is_service_account)

        # Get activity data
        activity_data = await self.get_activity_data(user_college)

        # Build initial state response
        state = {
            "type": "initial_state",
            "user": {
                "id": str(self.user.id),
                "is_service_account": is_service_account,
            },
            "access": access_data,
            "activity": activity_data,
            "queue": {
                "is_in_queue": is_in_queue,
            },
            "chat": None,
        }

        # If user has active chat, include chat data and auto-join chat group
        if active_chat:
            state["chat"] = await self.get_chat_data(active_chat)
            # Auto-join chat room
            self.current_chat = active_chat
            self.chat_group_name = f"chat_{active_chat.id}"
            await self.channel_layer.group_add(self.chat_group_name, self.channel_name)

        await self.send(text_data=json.dumps(state))

    async def get_access_data(self, college, is_service_account):
        """Get access permission data for user."""
        if is_service_account:
            return {
                "can_access": True,
                "message": "Service account - full access granted",
                "is_service_account": True,
            }

        if not college:
            return {
                "can_access": False,
                "reason": "no_college",
                "message": "No college assigned.",
            }

        is_active = await database_sync_to_async(lambda: college.is_active)()
        college_name = await database_sync_to_async(lambda: college.name)()
        
        if not is_active:
            return {
                "can_access": False,
                "reason": "college_inactive",
                "message": f"{college_name} is not currently active.",
                "college_name": college_name,
            }

        # Check time window
        window_open = await database_sync_to_async(MatchingService.is_college_window_open)(college)
        window_start = await database_sync_to_async(lambda: college.window_start)()
        window_end = await database_sync_to_async(lambda: college.window_end)()

        if not window_open:
            return {
                "can_access": False,
                "reason": "outside_window",
                "message": f"Chat is available {window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')}",
                "college_name": college_name,
                "window_start": window_start.strftime("%H:%M:%S"),
                "window_end": window_end.strftime("%H:%M:%S"),
            }

        # Calculate time remaining in window
        now = timezone.localtime()

        # Calculate seconds until window end
        window_end_dt = now.replace(
            hour=window_end.hour, minute=window_end.minute, second=window_end.second, microsecond=0
        )
        if window_end_dt < now:
            # Window ends tomorrow (crossed midnight)
            window_end_dt = window_end_dt.replace(day=now.day + 1)

        time_remaining = (window_end_dt - now).total_seconds()

        return {
            "can_access": True,
            "message": "Access granted",
            "college_name": college_name,
            "window_start": window_start.strftime("%H:%M:%S"),
            "window_end": window_end.strftime("%H:%M:%S"),
            "time_remaining_seconds": max(0, int(time_remaining)),
        }

    async def get_activity_data(self, college):
        """Get college activity statistics."""
        if not college:
            return {
                "college": "Service Account",
                "active_chats": 0,
                "waiting_count": 0,
                "registered_students": 0,
            }

        college_id = await database_sync_to_async(lambda: college.id)()
        college_name = await database_sync_to_async(lambda: college.name)()

        active_chats = await database_sync_to_async(
            Chat.objects.filter(college_id=college_id, is_active=True).count
        )()
        waiting_count = await database_sync_to_async(
            WaitingListEntry.objects.filter(college_id=college_id).count
        )()
        registered_students = await database_sync_to_async(
            User.objects.filter(college_id=college_id, is_active=True).count
        )()

        return {
            "college": college_name,
            "college_id": college_id,
            "active_chats": active_chats,
            "waiting_count": waiting_count,
            "registered_students": registered_students,
        }

    async def get_chat_data(self, chat):
        """Get chat data including messages."""
        chat_id = await database_sync_to_async(lambda: str(chat.id))()
        college_name = await database_sync_to_async(lambda: chat.college.name if chat.college else "Unknown")()
        created_at = await database_sync_to_async(lambda: chat.created_at.isoformat())()
        is_active = await database_sync_to_async(lambda: chat.is_active)()

        # Get messages
        messages = await database_sync_to_async(
            lambda: list(
                Message.objects.filter(chat=chat)
                .order_by("created_at")
                .values("id", "content", "sender_id", "message_type", "created_at")
            )
        )()

        formatted_messages = [
            {
                "id": str(msg["id"]),
                "content": msg["content"],
                "sender_id": str(msg["sender_id"]) if msg["sender_id"] else None,
                "message_type": msg["message_type"],
                "timestamp": msg["created_at"].isoformat(),
                "is_own": str(msg["sender_id"]) == str(self.user.id) if msg["sender_id"] else False,
            }
            for msg in messages
        ]

        return {
            "chat_id": chat_id,
            "college": college_name,
            "created_at": created_at,
            "is_active": is_active,
            "messages": formatted_messages,
        }

    # ==================== Queue Management ====================

    async def join_queue(self):
        """Add user to waiting queue."""
        user_college = await database_sync_to_async(lambda: self.user.college)()

        # Check if user already has an active chat
        active_chat = await database_sync_to_async(MatchingService.get_active_chat)(self.user)
        if active_chat:
            # Send chat data instead
            chat_data = await self.get_chat_data(active_chat)
            self.current_chat = active_chat
            self.chat_group_name = f"chat_{active_chat.id}"
            await self.channel_layer.group_add(self.chat_group_name, self.channel_name)
            await self.send(text_data=json.dumps({
                "type": "chat_matched",
                "chat": chat_data,
                "message": "You already have an active chat.",
            }))
            return

        # Add to waiting list
        await database_sync_to_async(MatchingService.add_to_waiting_list)(self.user, user_college)

        # Send immediate confirmation
        await self.send(text_data=json.dumps({
            "type": "queue_joined",
            "is_in_queue": True,
            "message": "You joined the queue. Looking for a match...",
        }))

        # Broadcast queue update to college
        await self.broadcast_activity_update()

        # Try to match
        await self.try_match()

    async def leave_queue(self):
        """Remove user from waiting queue."""
        user_college = await database_sync_to_async(lambda: self.user.college)()
        removed = await database_sync_to_async(MatchingService.remove_from_waiting_list)(self.user, user_college)

        # Send immediate confirmation
        await self.send(text_data=json.dumps({
            "type": "queue_left",
            "is_in_queue": False,
            "message": "You left the queue.",
        }))

        # Broadcast queue update
        if removed:
            await self.broadcast_activity_update()

    async def try_match(self):
        """Try to match users and create chat if possible."""
        user_college = await database_sync_to_async(lambda: self.user.college)()
        is_service_account = await database_sync_to_async(lambda: self.user.is_service_account)()

        if is_service_account:
            chat = await database_sync_to_async(MatchingService.try_match_service_account)()
        else:
            chat = await database_sync_to_async(MatchingService.try_match_users)(user_college, include_service_accounts=True)

        if chat:
            await self.notify_chat_match(chat)
        else:
            # Schedule delayed match attempt
            await self.schedule_delayed_match(user_college)

    async def schedule_delayed_match(self, college):
        """Schedule a delayed match attempt for users waiting 5+ seconds."""
        async def delayed_match():
            await asyncio.sleep(6)

            # Check if user is still in queue
            still_in_queue = await database_sync_to_async(
                WaitingListEntry.objects.filter(user=self.user).exists
            )()
            if not still_in_queue:
                return

            chat = await database_sync_to_async(MatchingService.try_match_users)(
                college, include_service_accounts=True
            )
            if chat:
                await self.notify_chat_match(chat)

        asyncio.create_task(delayed_match())

    async def notify_chat_match(self, chat):
        """Notify both participants about a match."""
        participants = await database_sync_to_async(chat.get_participants)()
        chat_data = await self.get_chat_data(chat)

        for participant in participants:
            await self.channel_layer.group_send(
                f"user_{participant.id}",
                {
                    "type": "chat_matched_handler",
                    "chat_id": str(chat.id),
                    "chat_data": chat_data,
                },
            )

        # Broadcast activity update
        await self.broadcast_activity_update()

    async def chat_matched_handler(self, event):
        """Handle chat match notification."""
        chat_id = event["chat_id"]
        chat_data = event.get("chat_data")

        # Join chat group
        self.chat_group_name = f"chat_{chat_id}"
        await self.channel_layer.group_add(self.chat_group_name, self.channel_name)

        # Load chat from DB if not provided
        if not chat_data:
            try:
                chat = await database_sync_to_async(Chat.objects.get)(id=chat_id)
                chat_data = await self.get_chat_data(chat)
                self.current_chat = chat
            except Chat.DoesNotExist:
                return

        await self.send(text_data=json.dumps({
            "type": "chat_matched",
            "chat": chat_data,
            "message": "Match found! Starting chat...",
        }))

    # ==================== Chat Management ====================

    async def join_chat(self, chat_id):
        """Join a specific chat room."""
        try:
            chat = await database_sync_to_async(Chat.objects.get)(id=chat_id)

            # Verify user is participant
            is_participant = await database_sync_to_async(chat.is_participant)(self.user)
            if not is_participant:
                await self.send(text_data=json.dumps({
                    "type": "error",
                    "code": "forbidden",
                    "message": "You are not a participant of this chat.",
                }))
                return

            # Leave previous chat if any
            if self.chat_group_name:
                await self.channel_layer.group_discard(self.chat_group_name, self.channel_name)

            # Join new chat group
            self.current_chat = chat
            self.chat_group_name = f"chat_{chat_id}"
            await self.channel_layer.group_add(self.chat_group_name, self.channel_name)

            chat_data = await self.get_chat_data(chat)
            await self.send(text_data=json.dumps({
                "type": "chat_joined",
                "chat": chat_data,
            }))

        except Chat.DoesNotExist:
            await self.send(text_data=json.dumps({
                "type": "error",
                "code": "not_found",
                "message": "Chat not found.",
            }))

    async def leave_chat(self):
        """Leave current chat room (but don't end it)."""
        if self.chat_group_name:
            await self.channel_layer.group_discard(self.chat_group_name, self.channel_name)
            self.chat_group_name = ""
            self.current_chat = None

        await self.send(text_data=json.dumps({
            "type": "chat_left",
        }))

    async def send_chat_message(self, content):
        """Save message and broadcast to chat room."""
        if not self.current_chat:
            await self.send(text_data=json.dumps({
                "type": "error",
                "message": "Not in a chat.",
            }))
            return

        # Save message
        message = await database_sync_to_async(Message.objects.create)(
            chat=self.current_chat, sender=self.user, content=content, message_type="text"
        )

        # Broadcast to chat room
        await self.channel_layer.group_send(
            self.chat_group_name,
            {
                "type": "chat_message_handler",
                "message_id": str(message.id),
                "content": content,
                "sender_id": str(self.user.id),
                "timestamp": message.created_at.isoformat(),
            },
        )

    async def chat_message_handler(self, event):
        """Handle chat message broadcast."""
        is_own = event["sender_id"] == str(self.user.id)
        await self.send(text_data=json.dumps({
            "type": "message",
            "message_id": event["message_id"],
            "content": event["content"],
            "sender_id": event["sender_id"],
            "timestamp": event["timestamp"],
            "message_type": "text",
            "is_own": is_own,
        }))

    async def end_chat(self):
        """End the current chat."""
        if not self.current_chat:
            return

        success = await database_sync_to_async(MatchingService.end_chat)(self.current_chat)

        if success:
            # Notify all participants
            await self.channel_layer.group_send(
                self.chat_group_name,
                {"type": "chat_ended_handler", "message": "Chat has been ended."},
            )
            # Broadcast activity update
            await self.broadcast_activity_update()

    async def chat_ended_handler(self, event):
        """Handle chat ended notification."""
        # Leave chat group
        if self.chat_group_name:
            await self.channel_layer.group_discard(self.chat_group_name, self.channel_name)
            self.chat_group_name = ""
            self.current_chat = None

        await self.send(text_data=json.dumps({
            "type": "chat_ended",
            "message": event["message"],
        }))

    async def broadcast_typing(self, is_typing):
        """Broadcast typing indicator."""
        if not self.chat_group_name:
            return

        event_type = "typing_start_handler" if is_typing else "typing_stop_handler"
        await self.channel_layer.group_send(
            self.chat_group_name,
            {"type": event_type, "user_id": str(self.user.id)},
        )

    async def typing_start_handler(self, event):
        """Handle typing start broadcast."""
        if event["user_id"] != str(self.user.id):
            await self.send(text_data=json.dumps({
                "type": "typing_start",
                "user_id": event["user_id"],
            }))

    async def typing_stop_handler(self, event):
        """Handle typing stop broadcast."""
        if event["user_id"] != str(self.user.id):
            await self.send(text_data=json.dumps({
                "type": "typing_stop",
                "user_id": event["user_id"],
            }))

    # ==================== Broadcasts ====================

    async def broadcast_activity_update(self):
        """Broadcast activity update to all users in college."""
        user_college = await database_sync_to_async(lambda: self.user.college)()
        activity_data = await self.get_activity_data(user_college)

        await self.channel_layer.group_send(
            self.college_group_name,
            {"type": "activity_update_handler", "activity": activity_data},
        )

    async def activity_update_handler(self, event):
        """Handle activity update broadcast."""
        await self.send(text_data=json.dumps({
            "type": "activity_update",
            "activity": event["activity"],
        }))

    async def presence_update(self, event):
        """Handle presence update broadcast."""
        if event.get("user_id") != str(self.user.id):
            await self.send(text_data=json.dumps({
                "type": "presence_update",
                "user_id": event["user_id"],
                "status": event["status"],
            }))

    # ==================== Group Message Handlers ====================

    async def trigger_match(self, _event):
        """Trigger matching attempt for this user."""
        # Check if user is in waiting list
        is_waiting = await database_sync_to_async(
            WaitingListEntry.objects.filter(user=self.user).exists
        )()
        if is_waiting:
            await self.try_match()
