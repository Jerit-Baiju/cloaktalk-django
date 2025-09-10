from typing import Optional, Tuple
from django.db import transaction
from base.models import WaitingListEntry, Chat, Message, College
from accounts.models import User


class MatchingService:
    """Service to handle matching users from the same college into chats."""
    
    @classmethod
    def add_to_waiting_list(cls, user: User, college: College) -> bool:
        """
        Add user to waiting list for their college.
        Returns True if added successfully, False if already in queue.
        """
        _, created = WaitingListEntry.objects.get_or_create(
            user=user,
            college=college
        )
        return created
    
    @classmethod
    def remove_from_waiting_list(cls, user: User, college: College = None) -> bool:
        """
        Remove user from waiting list.
        If college is not specified, removes from all waiting lists.
        """
        if college:
            deleted_count, _ = WaitingListEntry.objects.filter(
                user=user, college=college
            ).delete()
        else:
            deleted_count, _ = WaitingListEntry.objects.filter(user=user).delete()
        
        return deleted_count > 0
    
    @classmethod
    def get_waiting_count(cls, college: College) -> int:
        """Get number of users waiting for a match in the given college."""
        return WaitingListEntry.objects.filter(college=college).count()
    
    @classmethod
    def find_match(cls, college: College) -> Optional[Tuple[User, User]]:
        """
        Find two users from the same college to match.
        Returns tuple of (user1, user2) if match found, None otherwise.
        """
        waiting_entries = WaitingListEntry.objects.filter(
            college=college
        ).select_related('user').order_by('created_at')[:2]
        
        if len(waiting_entries) >= 2:
            return (waiting_entries[0].user, waiting_entries[1].user)
        return None
    
    @classmethod
    @transaction.atomic
    def create_chat(cls, user1: User, user2: User, college: College) -> Chat:
        """
        Create a new chat between two users and remove them from waiting list.
        """
        # Remove both users from waiting list
        WaitingListEntry.objects.filter(
            user__in=[user1, user2], college=college
        ).delete()
        
        # Create the chat
        chat = Chat.objects.create(
            college=college,
            participant1=user1,
            participant2=user2
        )
        
        # Create initial system message
        Message.objects.create(
            chat=chat,
            content="Chat started! You can now send messages anonymously.",
            message_type='system'
        )
        
        return chat
    
    @classmethod
    def try_match_users(cls, college: College) -> Optional[Chat]:
        """
        Try to match users in the waiting list for a college.
        Returns Chat object if successful match, None otherwise.
        """
        match = cls.find_match(college)
        if match:
            user1, user2 = match
            return cls.create_chat(user1, user2, college)
        return None
    
    @classmethod
    def get_active_chat(cls, user: User) -> Optional[Chat]:
        """Get the active chat for a user if any."""
        return Chat.objects.filter(
            models.Q(participant1=user) | models.Q(participant2=user),
            is_active=True
        ).first()
    
    @classmethod
    def end_chat(cls, chat: Chat) -> bool:
        """End an active chat."""
        if chat.is_active:
            chat.is_active = False
            chat.save()
            
            # Create system message about chat ending
            Message.objects.create(
                chat=chat,
                content="Chat has ended. Thank you for using CloakTalk!",
                message_type='system'
            )
            return True
        return False


# Import models after class definition to avoid circular imports
from django.db import models
