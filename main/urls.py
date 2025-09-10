from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from base.views import CollegeAccessView, CollegeStatusView, HomepageView

urlpatterns = [
    path("", HomepageView.as_view(), name="homepage"),
    path("api/", include("base.urls")),
    path("auth/", include("accounts.urls")),
    path("admin/", admin.site.urls),
    path("analytics/", include("analytics.urls")),
    # Legacy college endpoints for backward compatibility
    path("college/access/", CollegeAccessView.as_view(), name="legacy_college_access"),
    path("college/status/", CollegeStatusView.as_view(), name="legacy_college_status"),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
