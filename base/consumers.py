import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from base.models import Chat, Message, College
from base.services import MatchingService

logger = logging.getLogger(__name__)


class QueueConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for handling waiting queue functionality."""
    
    async def connect(self):
        """Handle WebSocket connection."""
        self.user = self.scope.get("user")
        
        if isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            await self.close(code=4001)
            return
        
        if not self.user.college:
            await self.close(code=4002)  # No college assigned
            return
            
        # Join college group for queue updates
        self.college_group_name = f"queue_{self.user.college.id}"
        await self.channel_layer.group_add(
            self.college_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send initial queue status
        await self.send_queue_status()
        
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, 'college_group_name'):
            await self.channel_layer.group_discard(
                self.college_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            action = data.get('action')
            
            if action == 'join_queue':
                await self.join_queue()
            elif action == 'leave_queue':
                await self.leave_queue()
            elif action == 'check_status':
                await self.send_queue_status()
                
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'error': 'Invalid JSON format'
            }))
    
    async def join_queue(self):
        """Add user to waiting queue."""
        added = await database_sync_to_async(MatchingService.add_to_waiting_list)(
            self.user, self.user.college
        )
        
        if added:
            # Notify college group about queue update
            await self.channel_layer.group_send(
                self.college_group_name,
                {
                    'type': 'queue_update',
                    'action': 'user_joined'
                }
            )
            
            # Try to find a match
            await self.try_match()
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Already in queue'
            }))
    
    async def leave_queue(self):
        """Remove user from waiting queue."""
        removed = await database_sync_to_async(MatchingService.remove_from_waiting_list)(
            self.user, self.user.college
        )
        
        if removed:
            await self.channel_layer.group_send(
                self.college_group_name,
                {
                    'type': 'queue_update',
                    'action': 'user_left'
                }
            )
    
    async def try_match(self):
        """Try to match users and create chat if possible."""
        chat = await database_sync_to_async(MatchingService.try_match_users)(
            self.user.college
        )
        
        if chat:
            # Notify both participants about the match
            participants = await database_sync_to_async(chat.get_participants)()
            for participant in participants:
                await self.channel_layer.group_send(
                    f"user_{participant.id}",
                    {
                        'type': 'chat_matched',
                        'chat_id': str(chat.id)
                    }
                )
            
            # Update queue for college group
            await self.channel_layer.group_send(
                self.college_group_name,
                {
                    'type': 'queue_update',
                    'action': 'match_created'
                }
            )
    
    async def send_queue_status(self):
        """Send current queue status to user."""
        count = await database_sync_to_async(MatchingService.get_waiting_count)(
            self.user.college
        )
        
        await self.send(text_data=json.dumps({
            'type': 'queue_status',
            'waiting_count': count,
            'college': self.user.college.name
        }))
    
    async def queue_update(self, event):
        """Handle queue update events."""
        await self.send_queue_status()
    
    async def chat_matched(self, event):
        """Handle chat match notification."""
        await self.send(text_data=json.dumps({
            'type': 'chat_matched',
            'chat_id': event['chat_id'],
            'message': 'Match found! Redirecting to chat...'
        }))


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for handling chat functionality."""
    
    async def connect(self):
        """Handle WebSocket connection for chat."""
        self.user = self.scope.get("user")
        self.chat_id = self.scope['url_route']['kwargs']['chat_id']
        
        if isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            await self.close(code=4001)
            return
        
        # Verify user is participant in this chat
        try:
            self.chat = await database_sync_to_async(Chat.objects.get)(
                id=self.chat_id, is_active=True
            )
            
            if not await database_sync_to_async(self.chat.is_participant)(self.user):
                await self.close(code=4003)  # Not authorized for this chat
                return
                
        except Chat.DoesNotExist:
            await self.close(code=4004)  # Chat not found
            return
        
        # Join chat room group
        self.room_group_name = f"chat_{self.chat_id}"
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send recent messages
        await self.send_recent_messages()
    
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )
    
    async def receive(self, text_data):
        """Handle incoming chat messages."""
        try:
            data = json.loads(text_data)
            action = data.get('action')
            
            if action == 'send_message':
                content = data.get('content', '').strip()
                if content:
                    await self.save_and_send_message(content)
            elif action == 'end_chat':
                await self.end_chat()
                
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'error': 'Invalid JSON format'
            }))
    
    async def save_and_send_message(self, content):
        """Save message to database and broadcast to chat room."""
        message = await database_sync_to_async(Message.objects.create)(
            chat=self.chat,
            sender=self.user,
            content=content,
            message_type='text'
        )
        
        # Broadcast message to room group
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_message',
                'message_id': str(message.id),
                'content': content,
                'sender_id': str(self.user.id),
                'timestamp': message.created_at.isoformat(),
                'is_own': False  # Will be set to True for sender
            }
        )
    
    async def end_chat(self):
        """End the current chat."""
        success = await database_sync_to_async(MatchingService.end_chat)(self.chat)
        
        if success:
            # Notify all participants that chat has ended
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_ended',
                    'message': 'Chat has been ended'
                }
            )
    
    async def send_recent_messages(self):
        """Send recent messages to the connected user."""
        messages = await database_sync_to_async(list)(
            Message.objects.filter(chat=self.chat)
            .select_related('sender')
            .order_by('-created_at')[:50]
        )
        
        for message in reversed(messages):
            await self.send(text_data=json.dumps({
                'type': 'message',
                'message_id': str(message.id),
                'content': message.content,
                'sender_id': str(message.sender.id) if message.sender else None,
                'message_type': message.message_type,
                'timestamp': message.created_at.isoformat(),
                'is_own': message.sender == self.user if message.sender else False
            }))
    
    async def chat_message(self, event):
        """Handle chat message events."""
        is_own = event['sender_id'] == str(self.user.id)
        
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message_id': event['message_id'],
            'content': event['content'],
            'sender_id': event['sender_id'],
            'timestamp': event['timestamp'],
            'is_own': is_own,
            'message_type': 'text'
        }))
    
    async def chat_ended(self, event):
        """Handle chat ended events."""
        await self.send(text_data=json.dumps({
            'type': 'chat_ended',
            'message': event['message']
        }))
