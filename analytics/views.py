from datetime import datetime, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Count, F, Max, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from base.models import Chat, College, Message

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
    total_colleges_with_students = users.filter(college__isnull=False).values("college").distinct().count()

    chats_by_day = chats.annotate(day=TruncDate("created_at")).values("day").annotate(c=Count("id")).order_by("day")
    chats_by_month = chats.annotate(month=TruncMonth("created_at")).values("month").annotate(c=Count("id")).order_by("month")

    chat_message_counts = chats.annotate(msgs=Count("messages")).order_by("-msgs")[:20]
    top_users = users.annotate(msgs=Count("message")).order_by("-msgs")[:20]

    # College registration statistics
    college_registrations = (
        users.select_related("college")
        .values("college__name", "college__id")
        .annotate(student_count=Count("id"))
        .filter(college__isnull=False)
        .order_by("-student_count")
    )

    context = {
        "kpis": {
            "total_users": total_users,
            "total_chats": total_chats,
            "total_messages": total_messages,
            "active_chats": active_chats,
            "total_colleges_with_students": total_colleges_with_students,
        },
        "chats_by_day": list(chats_by_day),
        "chats_by_month": list(chats_by_month),
        "chat_message_counts": chat_message_counts,
        "top_users": top_users,
        "college_registrations": college_registrations,
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
    chat = get_object_or_404(Chat.objects.select_related("participant1", "participant2", "college"), pk=chat_id)
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

    allowed_sorts = {
        "created_at",
        "-created_at",
        "chats_count",
        "-chats_count",
        "messages_sent",
        "-messages_sent",
        "name",
        "-name",
    }
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


@staff_member_required
def daily_analytics(request):
    """Daily analytics showing registrations, chats, and chat navigation for a specific day."""
    # Get the target date from query params, default to today
    date_str = request.GET.get("date")
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = timezone.now().date()
    else:
        target_date = timezone.now().date()

    # Calculate previous and next days for navigation
    prev_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)
    today = timezone.now().date()

    # Users registered on this day
    users_registered = User.objects.filter(created_at__date=target_date)
    users_registered_count = users_registered.count()

    # Chats created on this day
    chats_today = (
        Chat.objects.filter(created_at__date=target_date)
        .select_related("participant1", "participant2", "college")
        .annotate(msgs=Count("messages"), last_msg_at=Max("messages__created_at"))
        .order_by("created_at")
    )

    chats_today_count = chats_today.count()

    # Users who had chats on this day (either started a chat or participated in one)
    users_with_chats = User.objects.filter(
        Q(chats_as_participant1__created_at__date=target_date) | Q(chats_as_participant2__created_at__date=target_date)
    ).distinct()
    users_with_chats_count = users_with_chats.count()

    # Messages sent on this day
    messages_today = Message.objects.filter(created_at__date=target_date)
    messages_today_count = messages_today.count()

    # Pagination for chats
    paginator = Paginator(chats_today, 20)
    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    # Days with data for quick navigation
    days_with_chats = (
        Chat.objects.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(chat_count=Count("id"))
        .order_by("-day")[:30]
    )  # Last 30 days with data

    context = {
        "target_date": target_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "today": today,
        "users_registered_count": users_registered_count,
        "users_registered": users_registered,
        "chats_today_count": chats_today_count,
        "users_with_chats_count": users_with_chats_count,
        "messages_today_count": messages_today_count,
        "page_obj": page_obj,
        "days_with_chats": days_with_chats,
    }

    return render(request, "analytics/daily_analytics.html", context)


@staff_member_required
def daily_chat_reader(request):
    """Read through chats day by day with navigation."""
    # Get the target date from query params, default to today
    date_str = request.GET.get("date")
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            target_date = timezone.now().date()
    else:
        target_date = timezone.now().date()

    # Get chat index for navigation within the day
    chat_index = int(request.GET.get("index", 0))

    # Get all chats for this day
    chats_today = (
        Chat.objects.filter(created_at__date=target_date)
        .select_related("participant1", "participant2", "college")
        .order_by("created_at")
    )

    total_chats = chats_today.count()

    if total_chats == 0:
        # No chats for this day, try to find the next day with chats
        next_day_with_chats = (
            Chat.objects.filter(created_at__date__gt=target_date)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .distinct()
            .order_by("day")
            .first()
        )

        prev_day_with_chats = (
            Chat.objects.filter(created_at__date__lt=target_date)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .distinct()
            .order_by("-day")
            .first()
        )

        return render(
            request,
            "analytics/daily_chat_reader.html",
            {
                "target_date": target_date,
                "total_chats": 0,
                "next_day_with_chats": next_day_with_chats["day"] if next_day_with_chats else None,
                "prev_day_with_chats": prev_day_with_chats["day"] if prev_day_with_chats else None,
            },
        )

    # Ensure chat_index is within bounds
    if chat_index >= total_chats:
        chat_index = total_chats - 1
    elif chat_index < 0:
        chat_index = 0

    current_chat = chats_today[chat_index]
    messages = current_chat.messages.select_related("sender").all()

    # Navigation within day
    next_chat_index = chat_index + 1 if chat_index + 1 < total_chats else None
    prev_chat_index = chat_index - 1 if chat_index > 0 else None

    # Navigation to other days
    today = timezone.now().date()

    # Find days with chats for navigation
    prev_day_with_chats = (
        Chat.objects.filter(created_at__date__lt=target_date)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .distinct()
        .order_by("-day")
        .first()
    )

    next_day_with_chats = (
        Chat.objects.filter(created_at__date__gt=target_date)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .distinct()
        .order_by("day")
        .first()
    )

    context = {
        "target_date": target_date,
        "chat_index": chat_index,
        "total_chats": total_chats,
        "current_chat": current_chat,
        "messages": messages,
        "next_chat_index": next_chat_index,
        "prev_chat_index": prev_chat_index,
        "prev_day_with_chats": prev_day_with_chats["day"] if prev_day_with_chats else None,
        "next_day_with_chats": next_day_with_chats["day"] if next_day_with_chats else None,
        "today": today,
    }

    return render(request, "analytics/daily_chat_reader.html", context)


@staff_member_required
def colleges_list(request):
    """Overview list of colleges with basic aggregates and quick navigation."""
    q = request.GET.get("q")

    colleges = College.objects.all()
    if q:
        colleges = colleges.filter(Q(name__icontains=q) | Q(domain__icontains=q))

    # Aggregates
    users_per_college = (
        User.objects.filter(college__isnull=False)
        .values("college_id")
        .annotate(user_count=Count("id"))
    )
    users_map = {row["college_id"]: row["user_count"] for row in users_per_college}

    chats_per_college = Chat.objects.values("college_id").annotate(chat_count=Count("id"))
    chats_map = {row["college_id"]: row["chat_count"] for row in chats_per_college}

    msgs_per_college = (
        Message.objects.values("chat__college_id").annotate(msg_count=Count("id"))
    )
    msgs_map = {row["chat__college_id"]: row["msg_count"] for row in msgs_per_college}

    # Build list with aggregates
    items = []
    for college in colleges.order_by("name"):
        items.append(
            {
                "college": college,
                "user_count": users_map.get(college.id, 0),
                "chat_count": chats_map.get(college.id, 0),
                "msg_count": msgs_map.get(college.id, 0),
            }
        )

    return render(request, "analytics/colleges_list.html", {"items": items, "q": q})


@staff_member_required
def college_detail(request, college_id: int):
    """College specific analytics: message count, users count + list, chats count + list."""
    college = get_object_or_404(College, pk=college_id)

    # Filters and sorting
    q = request.GET.get("q")
    sort_chats = request.GET.get("sort_chats", "-last_msg_at")
    sort_users = request.GET.get("sort_users", "-messages_sent")

    # Users for this college
    users_qs = (
        User.objects.filter(college=college)
        .annotate(
            c1=Count("chats_as_participant1", distinct=True),
            c2=Count("chats_as_participant2", distinct=True),
            messages_sent=Count("message", distinct=True),
        )
        .annotate(chats_count=F("c1") + F("c2"))
    )
    if q:
        users_qs = users_qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(username__icontains=q))

    allowed_user_sorts = {
        "created_at",
        "-created_at",
        "chats_count",
        "-chats_count",
        "messages_sent",
        "-messages_sent",
        "name",
        "-name",
    }
    if sort_users not in allowed_user_sorts:
        sort_users = "-messages_sent"
    users_qs = users_qs.order_by(sort_users)

    users_count = users_qs.count()

    # Chats for this college
    chats_qs = (
        Chat.objects.filter(college=college)
        .select_related("participant1", "participant2", "college")
        .annotate(last_msg_at=Max("messages__created_at"), msgs=Count("messages"))
    )
    if q:
        chats_qs = chats_qs.filter(
            Q(participant1__name__icontains=q)
            | Q(participant1__email__icontains=q)
            | Q(participant2__name__icontains=q)
            | Q(participant2__email__icontains=q)
        )

    allowed_chat_sorts = {"created_at", "-created_at", "msgs", "-msgs", "last_msg_at", "-last_msg_at"}
    if sort_chats not in allowed_chat_sorts:
        sort_chats = "-last_msg_at"
    chats_qs = chats_qs.order_by(sort_chats)

    chats_count = chats_qs.count()

    # Message count for this college
    messages_count = Message.objects.filter(chat__college=college).count()

    # Pagination
    users_paginator = Paginator(users_qs, 25)
    users_page_obj = users_paginator.get_page(request.GET.get("users_page"))

    chats_paginator = Paginator(chats_qs, 25)
    chats_page_obj = chats_paginator.get_page(request.GET.get("chats_page"))

    context = {
        "college": college,
        "messages_count": messages_count,
        "users_count": users_count,
        "chats_count": chats_count,
        "users_page_obj": users_page_obj,
        "chats_page_obj": chats_page_obj,
        "sort_users": sort_users,
        "sort_chats": sort_chats,
        "q": q,
    }

    return render(request, "analytics/college_detail.html", context)
