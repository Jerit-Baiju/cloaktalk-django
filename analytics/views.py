from datetime import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, F, Max, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from base.models import Chat, Message

User = get_user_model()


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _common_filters(request):
    start = _parse_date(request.GET.get("start"))
    end = _parse_date(request.GET.get("end"))
    q = request.GET.get("q")
    college_id = request.GET.get("college")
    user_id = request.GET.get("user")
    return start, end, q, college_id, user_id


@staff_member_required
def analytics_dashboard(request):
    start, end, *_ = _common_filters(request)
    chats = Chat.objects.all()
    messages = Message.objects.all()
    users = User.objects.all()

    if start:
        chats = chats.filter(created_at__date__gte=start.date())
        messages = messages.filter(created_at__date__gte=start.date())
    if end:
        chats = chats.filter(created_at__date__lte=end.date())
        messages = messages.filter(created_at__date__lte=end.date())

    total_users = users.count()
    total_chats = chats.count()
    total_messages = messages.count()
    active_chats = chats.filter(is_active=True).count()

    chats_by_day = (
        chats.annotate(day=TruncDate("created_at")).values("day").annotate(c=Count("id")).order_by("day")
    )
    chats_by_month = (
        chats.annotate(month=TruncMonth("created_at")).values("month").annotate(c=Count("id")).order_by("month")
    )

    chat_message_counts = chats.annotate(msgs=Count("messages")).order_by("-msgs")[:20]
    top_users = users.annotate(msgs=Count("message")).order_by("-msgs")[:20]

    context = {
        "kpis": {
            "total_users": total_users,
            "total_chats": total_chats,
            "total_messages": total_messages,
            "active_chats": active_chats,
        },
        "chats_by_day": list(chats_by_day),
        "chats_by_month": list(chats_by_month),
        "chat_message_counts": chat_message_counts,
        "top_users": top_users,
    }
    return render(request, "analytics/dashboard.html", context)


@staff_member_required
def chats_list(request):
    start, end, q, college_id, user_id = _common_filters(request)
    qs = Chat.objects.select_related("participant1", "participant2", "college").annotate(
        last_msg_at=Max("messages__created_at"),
        msgs=Count("messages"),
    )
    if start:
        qs = qs.filter(created_at__date__gte=start.date())
    if end:
        qs = qs.filter(created_at__date__lte=end.date())
    if college_id:
        qs = qs.filter(college_id=college_id)
    if user_id:
        qs = qs.filter(Q(participant1_id=user_id) | Q(participant2_id=user_id))
    if q:
        qs = qs.filter(
            Q(participant1__name__icontains=q)
            | Q(participant1__email__icontains=q)
            | Q(participant2__name__icontains=q)
            | Q(participant2__email__icontains=q)
        )

    sort = request.GET.get("sort", "-last_msg_at")
    allowed_sorts = {"created_at", "-created_at", "msgs", "-msgs", "last_msg_at", "-last_msg_at"}
    if sort not in allowed_sorts:
        sort = "-last_msg_at"
    qs = qs.order_by(sort)

    paginator = Paginator(qs, 25)
    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    return render(request, "analytics/chats_list.html", {"page_obj": page_obj, "sort": sort})


@staff_member_required
def chat_detail(request, chat_id):
    chat = get_object_or_404(
        Chat.objects.select_related("participant1", "participant2", "college"), pk=chat_id
    )
    swap = request.GET.get("swap") == "1"
    messages = chat.messages.select_related("sender").all()

    next_chat = Chat.objects.filter(created_at__gt=chat.created_at).order_by("created_at").first()
    prev_chat = Chat.objects.filter(created_at__lt=chat.created_at).order_by("-created_at").first()

    context = {
        "chat": chat,
        "messages": messages,
        "swap": swap,
        "next_chat": next_chat,
        "prev_chat": prev_chat,
    }
    return render(request, "analytics/chat_detail.html", context)


@staff_member_required
def user_chats(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    qs = (
        Chat.objects.filter(Q(participant1=user) | Q(participant2=user))
        .select_related("participant1", "participant2", "college")
        .annotate(last_msg_at=Max("messages__created_at"), msgs=Count("messages"))
        .order_by("-last_msg_at")
    )

    start_with = request.GET.get("start")
    if start_with == "reader" and qs.exists():
        first = qs.first()
        return redirect("analytics:chat_detail", chat_id=first.id)

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "analytics/user_chats.html", {"user_obj": user, "page_obj": page_obj})


@staff_member_required
def chat_reader(request):
    start_id = request.GET.get("start")
    user_id = request.GET.get("user")

    qs = Chat.objects.select_related("participant1", "participant2", "college").order_by("created_at")
    if user_id:
        qs = qs.filter(Q(participant1_id=user_id) | Q(participant2_id=user_id))

    if start_id:
        try:
            current = qs.get(pk=start_id)
        except Chat.DoesNotExist as exc:
            raise Http404("Chat not found") from exc
    else:
        current = qs.first()
        if not current:
            return render(request, "analytics/reader_empty.html")

    next_chat = qs.filter(created_at__gt=current.created_at).first()
    prev_chat = qs.filter(created_at__lt=current.created_at).order_by("-created_at").first()

    messages = current.messages.select_related("sender").all()
    return render(
        request,
        "analytics/chat_reader.html",
        {
            "chat": current,
            "messages": messages,
            "next_chat": next_chat,
            "prev_chat": prev_chat,
        },
    )


@staff_member_required
def users_list(request):
    """List users with basic stats and search/sort."""
    q = request.GET.get("q")
    sort = request.GET.get("sort", "-created_at")

    users = (
        User.objects.select_related("college")
        .annotate(
            c1=Count("chats_as_participant1", distinct=True),
            c2=Count("chats_as_participant2", distinct=True),
            messages_sent=Count("message", distinct=True),
        )
        .annotate(chats_count=F("c1") + F("c2"))
    )

    if q:
        users = users.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(username__icontains=q))

    allowed_sorts = {"created_at", "-created_at", "chats_count", "-chats_count", "messages_sent", "-messages_sent", "name", "-name"}
    if sort not in allowed_sorts:
        sort = "-created_at"
    users = users.order_by(sort)

    paginator = Paginator(users, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "analytics/users_list.html", {"page_obj": page_obj, "sort": sort, "q": q})


@staff_member_required
def user_detail(request, user_id: int):
    """Detailed view for a single user including first_name and recent chats."""
    user = get_object_or_404(
        User.objects.select_related("college")
        .annotate(
            c1=Count("chats_as_participant1", distinct=True),
            c2=Count("chats_as_participant2", distinct=True),
            messages_sent=Count("message", distinct=True),
        )
        .annotate(chats_count=F("c1") + F("c2")),
        pk=user_id,
    )

    recent_chats = (
        Chat.objects.filter(Q(participant1=user) | Q(participant2=user))
        .select_related("participant1", "participant2", "college")
        .annotate(last_msg_at=Max("messages__created_at"), msgs=Count("messages"))
        .order_by("-last_msg_at")[:10]
    )

    return render(
        request,
        "analytics/user_detail.html",
        {
            "user_obj": user,
            "recent_chats": recent_chats,
        },
    )
