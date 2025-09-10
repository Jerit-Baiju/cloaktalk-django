from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views.generic import DetailView, ListView

from accounts.models import User
from base.models import Chat, Message


@method_decorator(staff_member_required, name="dispatch")
class UsersListView(ListView):
    """View to list all users with sorting and filtering options"""

    model = User
    template_name = "analytics/users_list.html"
    context_object_name = "users"
    paginate_by = 50

    def get_queryset(self):
        queryset = User.objects.annotate(
            chat_count=Count("chats_as_participant1") + Count("chats_as_participant2"),
            message_count=Count("message"),
            latest_activity=Max("message__created_at"),
        ).select_related("college")

        # Get sorting parameter
        sort_by = self.request.GET.get("sort", "created_at")
        order = self.request.GET.get("order", "desc")

        # Define sorting options
        sort_options = {
            "created_at": "created_at",
            "username": "username",
            "email": "email",
            "first_name": "first_name",
            "last_name": "last_name",
            "chat_count": "chat_count",
            "message_count": "message_count",
            "latest_activity": "latest_activity",
            "is_verified": "is_verified",
        }

        if sort_by in sort_options:
            order_prefix = "-" if order == "desc" else ""
            queryset = queryset.order_by(f"{order_prefix}{sort_options[sort_by]}")

        # Search functionality
        search = self.request.GET.get("search", "")
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search)
                | Q(email__icontains=search)
                | Q(name__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_sort"] = self.request.GET.get("sort", "created_at")
        context["current_order"] = self.request.GET.get("order", "desc")
        context["search_query"] = self.request.GET.get("search", "")
        context["total_users"] = User.objects.count()
        context["verified_users"] = User.objects.filter(is_verified=True).count()
        context["total_chats"] = Chat.objects.count()
        context["total_messages"] = Message.objects.count()
        return context


@method_decorator(staff_member_required, name="dispatch")
class UserDetailView(DetailView):
    """View to show details of a specific user and their chats"""

    model = User
    template_name = "analytics/user_detail.html"
    context_object_name = "user"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.get_object()

        # Get all chats for this user
        chats = (
            Chat.objects.filter(Q(participant1=user) | Q(participant2=user))
            .annotate(message_count=Count("messages"), latest_message=Max("messages__created_at"))
            .select_related("college", "participant1", "participant2")
        )

        # Sort chats
        sort_by = self.request.GET.get("sort", "latest_message")
        order = self.request.GET.get("order", "desc")

        sort_options = {
            "created_at": "created_at",
            "latest_message": "latest_message",
            "message_count": "message_count",
            "college": "college__name",
        }

        if sort_by in sort_options:
            order_prefix = "-" if order == "desc" else ""
            chats = chats.order_by(f"{order_prefix}{sort_options[sort_by]}")

        # Paginate chats
        paginator = Paginator(chats, 20)
        page = self.request.GET.get("page", 1)
        chats_page = paginator.get_page(page)

        # Calculate user statistics
        context["chats"] = chats_page
        context["current_sort"] = sort_by
        context["current_order"] = order
        context["total_chats"] = chats.count()
        context["total_messages"] = Message.objects.filter(sender=user).count()
        context["user_stats"] = {
            "total_chats": chats.count(),
            "total_messages_sent": Message.objects.filter(sender=user).count(),
            "active_chats": chats.filter(is_active=True).count(),
            "colleges_participated": chats.values("college").distinct().count(),
        }

        return context


@method_decorator(staff_member_required, name="dispatch")
class ChatDetailView(DetailView):
    """View to show details of a specific chat and its messages"""

    model = Chat
    template_name = "analytics/chat_detail.html"
    context_object_name = "chat"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        chat = self.get_object()

        # Get all messages for this chat
        messages = chat.messages.all().select_related("sender")

        # Sort messages
        sort_by = self.request.GET.get("sort", "created_at")
        order = self.request.GET.get("order", "asc")

        if sort_by == "created_at":
            order_prefix = "-" if order == "desc" else ""
            messages = messages.order_by(f"{order_prefix}created_at")

        # Paginate messages
        paginator = Paginator(messages, 50)
        page = self.request.GET.get("page", 1)
        messages_page = paginator.get_page(page)

        # Calculate chat statistics
        participant1_messages = messages.filter(sender=chat.participant1).count()
        participant2_messages = messages.filter(sender=chat.participant2).count()
        system_messages = messages.filter(message_type="system").count()

        context["messages"] = messages_page
        context["current_sort"] = sort_by
        context["current_order"] = order
        context["chat_stats"] = {
            "total_messages": messages.count(),
            "participant1_messages": participant1_messages,
            "participant2_messages": participant2_messages,
            "system_messages": system_messages,
            "chat_duration": self._get_chat_duration(messages),
        }

        return context

    def _get_chat_duration(self, messages):
        """Calculate the duration of the chat"""
        if not messages.exists():
            return "No messages"

        first_message = messages.first()
        last_message = messages.last()

        if first_message.created_at == last_message.created_at:
            return "Single message"

        duration = last_message.created_at - first_message.created_at

        if duration.days > 0:
            return f"{duration.days} days, {duration.seconds // 3600} hours"
        elif duration.seconds >= 3600:
            return f"{duration.seconds // 3600} hours, {(duration.seconds % 3600) // 60} minutes"
        else:
            return f"{duration.seconds // 60} minutes"


@staff_member_required
def analytics_dashboard(request):
    """Main analytics dashboard with overview statistics"""
    context = {
        "total_users": User.objects.count(),
        "verified_users": User.objects.filter(is_verified=True).count(),
        "total_chats": Chat.objects.count(),
        "active_chats": Chat.objects.filter(is_active=True).count(),
        "total_messages": Message.objects.count(),
        "recent_users": User.objects.order_by("-created_at")[:10],
        "recent_chats": Chat.objects.order_by("-created_at")[:10].select_related("college", "participant1", "participant2"),
        "top_colleges": Chat.objects.values("college__name").annotate(chat_count=Count("id")).order_by("-chat_count")[:10],
    }
    return render(request, "analytics/dashboard.html", context)
