from datetime import datetime
from typing import Optional, Tuple

from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import User
from base.models import Chat, College, Message, WaitingListEntry


class MatchingService:
    """Service to handle matching users from the same college into chats."""

    @classmethod
    def add_to_waiting_list(cls, user: User, college: College = None) -> bool:
        """
        Add user to waiting list for their college.
        Service accounts can be added without a college.
        Returns True if added successfully, False if already in queue.
        """
        # Service accounts don't need a college
        if user.is_service_account:
            college = college or user.college  # Use None if no college

        if not college and not user.is_service_account:
            raise ValueError("Regular users must have a college")

        _, created = WaitingListEntry.objects.get_or_create(
            user=user, college=college)
        return created

    @classmethod
    def remove_from_waiting_list(cls, user: User, college: College = None) -> bool:
        """
        Remove user from waiting list.
        If college is not specified, removes from all waiting lists.
        """
        if college:
            deleted_count, _ = WaitingListEntry.objects.filter(
                user=user, college=college).delete()
        else:
            deleted_count, _ = WaitingListEntry.objects.filter(
                user=user).delete()

        return deleted_count > 0

    @classmethod
    def get_waiting_count(cls, college: College) -> int:
        """Get number of users waiting for a match in the given college."""
        return WaitingListEntry.objects.filter(college=college).count()

    @classmethod
    def find_match(cls, college: College = None, include_service_accounts: bool = False) -> Optional[Tuple[User, User]]:
        """
        Find two users from the same college to match using smart algorithm.
        If include_service_accounts is True, also considers service accounts from any college.
        Priority:
        1. Fresh users (who haven't chatted with anyone in queue)
        2. Users who haven't chatted with each other
        3. If all have chatted, pick oldest chat pair after 5 seconds wait

        Returns tuple of (user1, user2) if match found, None otherwise.
        """
        # Build query for waiting entries
        if college:
            # Get users from specific college, optionally including service accounts
            if include_service_accounts:
                waiting_entries = WaitingListEntry.objects.filter(
                    Q(college=college) | Q(user__is_service_account=True)
                ).select_related("user").order_by("created_at")
            else:
                waiting_entries = WaitingListEntry.objects.filter(
                    college=college).select_related("user").order_by("created_at")
        else:
            # No college specified, get all service accounts
            waiting_entries = WaitingListEntry.objects.filter(
                user__is_service_account=True
            ).select_related("user").order_by("created_at")

        if len(waiting_entries) < 2:
            return None

        users = [entry.user for entry in waiting_entries]

        # Strategy 1: Find pairs where at least one user is completely fresh (never chatted)
        fresh_users = []
        experienced_users = []

        for user in users:
            if cls.has_any_chat_history(user):
                experienced_users.append(user)
            else:
                fresh_users.append(user)

        # If we have at least one fresh user, pair them with anyone
        if fresh_users:
            if len(fresh_users) >= 2:
                # Two fresh users - perfect match
                return (fresh_users[0], fresh_users[1])
            else:
                # One fresh user, pair with any experienced user
                if experienced_users:
                    return (fresh_users[0], experienced_users[0])

        # Strategy 2: All users have some chat history, find pairs who haven't chatted together
        for i, user1 in enumerate(experienced_users):
            for user2 in experienced_users[i + 1:]:
                if not cls.have_users_chatted_before(user1, user2):
                    return (user1, user2)

        # Strategy 3: All users have chatted with each other before
        # Check if enough time has passed (5 seconds) since they joined queue
        now = timezone.now()

        # Find the pair with the oldest most recent chat
        best_pair = None
        oldest_chat_time = None

        for i, user1 in enumerate(experienced_users):
            user1_entry = next(
                entry for entry in waiting_entries if entry.user == user1)

            # Check if user1 has been waiting for at least 5 seconds
            if (now - user1_entry.created_at).total_seconds() < 5:
                continue

            for user2 in experienced_users[i + 1:]:
                user2_entry = next(
                    entry for entry in waiting_entries if entry.user == user2)

                # Check if user2 has been waiting for at least 5 seconds
                if (now - user2_entry.created_at).total_seconds() < 5:
                    continue

                # Find their most recent chat together
                most_recent_chat_time = cls.get_most_recent_chat_time(
                    user1, user2)

                if oldest_chat_time is None or (most_recent_chat_time and most_recent_chat_time < oldest_chat_time):
                    oldest_chat_time = most_recent_chat_time
                    best_pair = (user1, user2)

        return best_pair

    @classmethod
    def has_any_chat_history(cls, user: User) -> bool:
        """Check if user has any chat history at all."""
        return Chat.objects.filter(Q(participant1=user) | Q(participant2=user)).exists()

    @classmethod
    def have_users_chatted_before(cls, user1: User, user2: User) -> bool:
        """Check if two users have had any chat together before."""
        return Chat.objects.filter(
            (Q(participant1=user1) & Q(participant2=user2)) | (
                Q(participant1=user2) & Q(participant2=user1))
        ).exists()

    @classmethod
    def get_most_recent_chat_time(cls, user1: User, user2: User) -> Optional[datetime]:
        """Get the creation time of the most recent chat between two users."""
        most_recent_chat = (
            Chat.objects.filter(
                (Q(participant1=user1) & Q(participant2=user2)) | (
                    Q(participant1=user2) & Q(participant2=user1))
            )
            .order_by("-created_at")
            .first()
        )

        return most_recent_chat.created_at if most_recent_chat else None

    @classmethod
    def get_queue_waiting_stats(cls, college: College) -> dict:
        """Get statistics about users waiting in queue."""
        waiting_entries = WaitingListEntry.objects.filter(
            college=college).select_related("user").order_by("created_at")

        if not waiting_entries:
            return {
                "total_waiting": 0,
                "fresh_users": 0,
                "experienced_users": 0,
                "ready_for_matching": False,
                "users_waiting_over_5_seconds": 0,
            }

        users = [entry.user for entry in waiting_entries]
        fresh_users = sum(
            1 for user in users if not cls.has_any_chat_history(user))
        experienced_users = len(users) - fresh_users

        # Count users who have been waiting over 5 seconds
        now = timezone.now()
        users_waiting_over_5_seconds = sum(1 for entry in waiting_entries if (
            now - entry.created_at).total_seconds() >= 5)

        # Check if matching is possible
        ready_for_matching = False
        if len(users) >= 2:
            if fresh_users >= 1:  # At least one fresh user can be matched
                ready_for_matching = True
            elif users_waiting_over_5_seconds >= 2:  # Two users have waited 5+ seconds
                ready_for_matching = True
            else:
                # Check if any pair hasn't chatted before
                for i, user1 in enumerate(users):
                    for user2 in users[i + 1:]:
                        if not cls.have_users_chatted_before(user1, user2):
                            ready_for_matching = True
                            break
                    if ready_for_matching:
                        break

        return {
            "total_waiting": len(users),
            "fresh_users": fresh_users,
            "experienced_users": experienced_users,
            "ready_for_matching": ready_for_matching,
            "users_waiting_over_5_seconds": users_waiting_over_5_seconds,
        }

    @classmethod
    @transaction.atomic
    def create_chat(cls, user1: User, user2: User, college: College = None) -> Chat:
        """
        Create a new chat between two users and remove them from waiting list.
        College is optional for service account chats.
        """
        # Determine college for the chat
        # Service accounts can chat across colleges, so college may be None
        if not college:
            # Try to use college from regular users
            if not user1.is_service_account and user1.college:
                college = user1.college
            elif not user2.is_service_account and user2.college:
                college = user2.college

        # Remove both users from waiting list
        WaitingListEntry.objects.filter(user__in=[user1, user2]).delete()

        # Create the chat
        chat = Chat.objects.create(
            college=college, participant1=user1, participant2=user2)

        # Create initial system message
        Message.objects.create(
            chat=chat, content="Chat started! You can now send messages anonymously.", message_type="system"
        )

        return chat

    @classmethod
    def try_match_service_account(cls) -> Optional[Chat]:
        """
        Try to match a service account with any waiting user from any college.
        Returns Chat object if successful match, None otherwise.
        """
        # Get all service accounts in queue
        service_entries = WaitingListEntry.objects.filter(
            user__is_service_account=True
        ).select_related("user")

        if not service_entries.exists():
            return None

        # Get all colleges with waiting users
        colleges_with_users = College.objects.filter(
            waitinglistentry__isnull=False
        ).distinct()

        # Try to match service account with any waiting user from any college
        for college in colleges_with_users:
            chat = cls.try_match_users(college, include_service_accounts=True)
            if chat:
                return chat

        return None

    @classmethod
    def try_match_users(cls, college: College = None, include_service_accounts: bool = False) -> Optional[Chat]:
        """
        Try to match users in the waiting list for a college.
        If include_service_accounts is True, also considers service accounts.
        Returns Chat object if successful match, None otherwise.
        """
        # Keep attempting to find a valid pair (defensive against stale entries)

        while True:
            match = cls.find_match(college, include_service_accounts)
            if not match:
                return None

            user1, user2 = match
            user1_active = cls.get_active_chat(user1)
            user2_active = cls.get_active_chat(user2)

            # If either already has an active chat, remove their waiting entry and try again
            removed_any = False
            if user1_active:
                WaitingListEntry.objects.filter(user=user1).delete()
                removed_any = True
            if user2_active:
                WaitingListEntry.objects.filter(user=user2).delete()
                removed_any = True

            if removed_any:
                continue

            # Neither user has an active chat -> create a new chat
            # Determine college for the chat
            chat_college = college
            if user1.is_service_account or user2.is_service_account:
                # For service account chats, use college of the non-service user
                if not user1.is_service_account:
                    chat_college = user1.college
                elif not user2.is_service_account:
                    chat_college = user2.college
                # else both are service accounts, college can be None

            return cls.create_chat(user1, user2, chat_college)

    @classmethod
    def get_active_chat(cls, user: User) -> Optional[Chat]:
        """Get the active chat for a user if any."""
        return Chat.objects.filter(models.Q(participant1=user) | models.Q(participant2=user), is_active=True).first()

    @classmethod
    def end_chat(cls, chat: Chat) -> bool:
        """End an active chat."""
        if chat.is_active:
            chat.is_active = False
            chat.save()

            # Create system message about chat ending
            Message.objects.create(
                chat=chat, content="Chat has ended. Thank you for using CloakTalk!", message_type="system"
            )
            return True
        return False


# Import models after class definition to avoid circular imports
