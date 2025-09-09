from datetime import datetime, timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from base.models import College


class CollegeAccessView(APIView):
    """
    Check if the current user can access the application based on their college's
    active status and time window settings.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

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
                college_name = domain.replace('.', ' ').title()
                if college_name.endswith(' Edu'):
                    college_name = college_name[:-4] + ' University'
                elif college_name.endswith(' Ac In'):
                    college_name = college_name[:-6] + ' College'
                elif domain.lower() in {"gmail.com", "googlemail.com"}:
                    college_name = "Gmail Users"

                college = College.objects.create(
                    name=college_name,
                    domain=domain,
                    window_start='20:00:00',  # Default 8 PM
                    window_end='21:00:00',    # Default 9 PM
                    is_active=False           # New colleges start inactive
                )

            # Assign college to user
            user.college = college
            user.save()

        college = user.college

        # Check if college is active
        if not college.is_active:
            return Response({
                'can_access': False,
                'reason': 'college_inactive',
                'message': f'Access for {college.name} is currently disabled',
                'college_name': college.name,
                'college_domain': college.domain
            }, status=status.HTTP_403_FORBIDDEN)

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
            return Response({
                'can_access': False,
                'reason': 'outside_window',
                'message': f'Access is only available between {college.window_start.strftime("%H:%M")} and {college.window_end.strftime("%H:%M")}',
                'college_name': college.name,
                'window_start': college.window_start.strftime('%H:%M:%S'),
                'window_end': college.window_end.strftime('%H:%M:%S')
            }, status=status.HTTP_403_FORBIDDEN)

        # User can access
        return Response({
            'can_access': True,
            'message': 'Access granted',
            'college_name': college.name,
            'window_start': college.window_start.strftime('%H:%M:%S'),
            'window_end': college.window_end.strftime('%H:%M:%S'),
            'time_remaining_seconds': self._calculate_time_remaining(current_time, college.window_end)
        }, status=status.HTTP_200_OK)
    
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
                college_name = domain.replace('.', ' ').title()
                if college_name.endswith(' Edu'):
                    college_name = college_name[:-4] + ' University'
                    
                elif college_name.endswith(' Ac In'):
                    college_name = college_name[:-6] + ' College'
                elif domain.lower() in {"gmail.com", "googlemail.com"}:
                    college_name = "Gmail Users"

                college = College.objects.create(
                    name=college_name,
                    domain=domain,
                    window_start='20:00:00',  # Default 8 PM
                    window_end='21:00:00',    # Default 9 PM
                    is_active=False           # New colleges start inactive
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

        return Response({
            'has_college': True,
            'college': {
                'id': college.id,
                'name': college.name,
                'domain': college.domain,
                'is_active': college.is_active,
                'window_start': college.window_start.strftime('%H:%M:%S'),
                'window_end': college.window_end.strftime('%H:%M:%S'),
                'currently_in_window': in_window,
                'can_access': college.is_active and in_window
            }
        }, status=status.HTTP_200_OK)
