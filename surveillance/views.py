import logging
import secrets
from datetime import timedelta

from django.utils import timezone
from django.db import transaction
from django.db.models import Avg, Count, Prefetch, Q, Sum
from django.db.models.functions import TruncDate
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.pagination import PageNumberPagination
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from django.http import HttpResponse, StreamingHttpResponse
from django.utils.html import escape
from django.utils.http import http_date

from organizations.models import Organization, OrganizationMember
from organizations.permissions import IsOrgMember, IsOrgAdmin
from .models import (
    Monitor, ApiLog, Incident, IncidentUpdate,
    StatusPage, StatusPageMonitor, Subscriber,
    AlertChannel, ApiToken, MonitorHourlyStat, MaintenanceWindow,
)
from .serializers import (
    MonitorListSerializer,
    MonitorDetailSerializer,
    MonitorCreateSerializer,
    MonitorUpdateSerializer,
    ApiLogSerializer,
    IncidentSerializer,
    IncidentPostUpdateSerializer,
    UptimeWindowSerializer,
    StatusPageSerializer,
    StatusPageWriteSerializer,
    PublicIncidentSerializer,
    SubscribeSerializer,
    AlertChannelSerializer,
    AlertChannelWriteSerializer,
    ApiTokenSerializer,
    ApiTokenCreateSerializer,
    MaintenanceWindowSerializer,
    MaintenanceWindowWriteSerializer,
)
from .alerts import send_test_message
from .authentication import generate_token
from .tasks import notify_incident, auto_resolve_incident
from .events import event_stream

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# How many recent checks the heartbeat strip shows per monitor.
HEARTBEAT_BEATS = 40


class CheckHistoryPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def _get_org_or_404(org_id):
    try:
        return Organization.objects.get(pk=org_id)
    except Organization.DoesNotExist:
        return None


def _get_monitor_or_404(org, monitor_id):
    """Get a non-archived monitor belonging to the org."""
    try:
        return Monitor.objects.get(pk=monitor_id, organization=org, deleted_at__isnull=True)
    except Monitor.DoesNotExist:
        return None


# ---------------------------------------------------------------------------
# Monitor List + Create
# ---------------------------------------------------------------------------

class MonitorListCreateView(APIView):
    """
    GET  /api/v1/orgs/{orgId}/monitors/  — List monitors
    POST /api/v1/orgs/{orgId}/monitors/  — Create monitor
    """

    def get_permissions(self):
        return [IsAuthenticated(), IsOrgMember()]

    def get(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Attach the last N checks per monitor in ONE extra query via Prefetch,
        # so the heartbeat strip and uptime badge don't cost a request (or a
        # query) per row. Without this the list is an N+1 the moment the
        # dashboard shows more than a handful of monitors.
        recent = ApiLog.objects.order_by('-checked_at').only(
            'monitor_id', 'result', 'response_time_ms', 'checked_at',
        )
        monitors = Monitor.objects.filter(
            organization=org,
            deleted_at__isnull=True,
        ).prefetch_related(
            Prefetch('api_logs', queryset=recent, to_attr='recent_checks_all')
        ).order_by('-created_at')

        monitors = list(monitors)
        for m in monitors:
            # Slice in Python: a per-row LIMIT is not expressible in a single
            # prefetch query, and HEARTBEAT_BEATS is small.
            m.recent_checks = m.recent_checks_all[:HEARTBEAT_BEATS]

        serializer = MonitorListSerializer(monitors, many=True)
        return Response(serializer.data)

    def post(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = MonitorCreateSerializer(
            data=request.data,
            context={'request': request, 'organization': org},
        )
        if serializer.is_valid():
            monitor = serializer.save()
            return Response(
                MonitorDetailSerializer(monitor, context={'request': request}).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Monitor Detail + Update + Archive (soft delete)
# ---------------------------------------------------------------------------

class MonitorDetailView(APIView):
    """
    GET    /api/v1/orgs/{orgId}/monitors/{monitorId}/
    PATCH  /api/v1/orgs/{orgId}/monitors/{monitorId}/
    DELETE /api/v1/orgs/{orgId}/monitors/{monitorId}/  — Archive (soft delete, admin only)
    """

    def get_permissions(self):
        if self.request.method == 'DELETE':
            return [IsAuthenticated(), IsOrgAdmin()]
        return [IsAuthenticated(), IsOrgMember()]

    def get(self, request, orgId, monitorId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        monitor = _get_monitor_or_404(org, monitorId)
        if not monitor:
            return Response({'detail': 'Monitor not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(MonitorDetailSerializer(monitor, context={'request': request}).data)

    def patch(self, request, orgId, monitorId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        monitor = _get_monitor_or_404(org, monitorId)
        if not monitor:
            return Response({'detail': 'Monitor not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = MonitorUpdateSerializer(monitor, data=request.data, partial=True)
        if serializer.is_valid():
            updated = serializer.save()
            return Response(MonitorDetailSerializer(updated, context={'request': request}).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, orgId, monitorId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        monitor = _get_monitor_or_404(org, monitorId)
        if not monitor:
            return Response({'detail': 'Monitor not found.'}, status=status.HTTP_404_NOT_FOUND)

        monitor.deleted_at = timezone.now()
        monitor.status = 'archived'
        monitor.save(update_fields=['deleted_at', 'status', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Pause / Resume
# ---------------------------------------------------------------------------

class MonitorPauseView(APIView):
    """POST /api/v1/orgs/{orgId}/monitors/{monitorId}/pause/"""
    permission_classes = [IsAuthenticated, IsOrgMember]

    def post(self, request, orgId, monitorId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        monitor = _get_monitor_or_404(org, monitorId)
        if not monitor:
            return Response({'detail': 'Monitor not found.'}, status=status.HTTP_404_NOT_FOUND)

        if monitor.status == 'paused':
            return Response({'detail': 'Monitor is already paused.'}, status=status.HTTP_409_CONFLICT)

        monitor.status = 'paused'
        monitor.save(update_fields=['status', 'updated_at'])
        return Response({'detail': 'Monitor paused.', 'status': monitor.status})


class MonitorResumeView(APIView):
    """POST /api/v1/orgs/{orgId}/monitors/{monitorId}/resume/"""
    permission_classes = [IsAuthenticated, IsOrgMember]

    def post(self, request, orgId, monitorId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        monitor = _get_monitor_or_404(org, monitorId)
        if not monitor:
            return Response({'detail': 'Monitor not found.'}, status=status.HTTP_404_NOT_FOUND)

        if monitor.status == 'active':
            return Response({'detail': 'Monitor is already active.'}, status=status.HTTP_409_CONFLICT)
        if monitor.status == 'archived':
            return Response({'detail': 'Cannot resume an archived monitor.'}, status=status.HTTP_400_BAD_REQUEST)

        monitor.status = 'active'
        monitor.save(update_fields=['status', 'updated_at'])
        return Response({'detail': 'Monitor resumed.', 'status': monitor.status})


# ---------------------------------------------------------------------------
# Check History (paginated)
# ---------------------------------------------------------------------------

class MonitorChecksView(APIView):
    """
    GET /api/v1/orgs/{orgId}/monitors/{monitorId}/checks/
    Optional query params: ?region=<region>&result=<success|failure>&page=1&page_size=50
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def get(self, request, orgId, monitorId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        monitor = _get_monitor_or_404(org, monitorId)
        if not monitor:
            return Response({'detail': 'Monitor not found.'}, status=status.HTTP_404_NOT_FOUND)

        qs = ApiLog.objects.filter(monitor=monitor).order_by('-checked_at')

        region = request.query_params.get('region')
        if region:
            qs = qs.filter(region=region)

        result = request.query_params.get('result')
        if result in ('success', 'failure'):
            qs = qs.filter(result=result)

        paginator = CheckHistoryPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = ApiLogSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ---------------------------------------------------------------------------
# Uptime Stats
# ---------------------------------------------------------------------------

# 30/60/90 come straight from the "historical health tracking" goal; 24h and 7d
# are what an operator actually looks at during and just after an incident.
def _uptime_for_window(monitor, label, days, now):
    """
    Uptime for one window, served from hourly rollups.

    This used to COUNT/AVG raw check rows, so the 90-day window scanned ~130k
    rows per monitor and got slower every day the product ran. Rollups make it
    ~2,160 rows and let raw rows be purged on a retention schedule.

    Recent checks (the current, not-yet-rolled-up hour) are added from the raw
    table so the numbers don't lag by up to ten minutes.
    """
    since = now - timedelta(days=days)
    rolled_until = now.replace(minute=0, second=0, microsecond=0)

    agg = MonitorHourlyStat.objects.filter(
        monitor=monitor, hour__gte=since, hour__lt=rolled_until,
    ).aggregate(
        total=Sum('total_checks'),
        failed=Sum('failed_checks'),
        avg=Avg('avg_response_time_ms'),
        p50=Avg('p50_response_time_ms'),
        p95=Avg('p95_response_time_ms'),
        p99=Avg('p99_response_time_ms'),
    )

    total = agg['total'] or 0
    failed = agg['failed'] or 0
    avg_rt = agg['avg']

    # Top up with the current hour, which the rollup hasn't covered yet.
    recent = ApiLog.objects.filter(monitor=monitor, checked_at__gte=rolled_until)
    recent_total = recent.count()
    if recent_total:
        recent_failed = recent.filter(result='failure').count()
        recent_avg = recent.filter(result='success').aggregate(a=Avg('response_time_ms'))['a']
        total += recent_total
        failed += recent_failed
        if recent_avg is not None:
            avg_rt = recent_avg if avg_rt is None else (avg_rt + recent_avg) / 2

    successful = total - failed
    return {
        'window': label,
        'total_checks': total,
        'successful_checks': successful,
        'failed_checks': failed,
        'uptime_pct': round((successful / total * 100) if total else 100.0, 4),
        'avg_response_time_ms': round(avg_rt, 2) if avg_rt is not None else None,
        'p50_response_time_ms': round(agg['p50']) if agg['p50'] is not None else None,
        'p95_response_time_ms': round(agg['p95']) if agg['p95'] is not None else None,
        'p99_response_time_ms': round(agg['p99']) if agg['p99'] is not None else None,
    }


UPTIME_WINDOWS = {
    '24h': 1,
    '7d': 7,
    '30d': 30,
    '60d': 60,
    '90d': 90,
}


class MonitorUptimeView(APIView):
    """
    GET /api/v1/orgs/{orgId}/monitors/{monitorId}/uptime/
    Returns aggregated stats for 24h, 7d, 30d, 90d windows.
    Optional: ?window=7d to get a single window.
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def get(self, request, orgId, monitorId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        monitor = _get_monitor_or_404(org, monitorId)
        if not monitor:
            return Response({'detail': 'Monitor not found.'}, status=status.HTTP_404_NOT_FOUND)

        requested_window = request.query_params.get('window')
        windows_to_compute = (
            {requested_window: UPTIME_WINDOWS[requested_window]}
            if requested_window in UPTIME_WINDOWS
            else UPTIME_WINDOWS
        )

        now = timezone.now()
        results = []

        for label, days in windows_to_compute.items():
            results.append(_uptime_for_window(monitor, label, days, now))

        serializer = UptimeWindowSerializer(results, many=True)
        return Response(serializer.data)


# ---------------------------------------------------------------------------
# Incident Views
# ---------------------------------------------------------------------------

class IncidentListView(APIView):
    """
    GET /api/v1/orgs/{orgId}/incidents/  — List open (and recent) incidents
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def get(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)

        qs = Incident.objects.filter(organization=org).select_related('monitor')

        # ?status=investigating|identified|monitoring|resolved
        incident_status = request.query_params.get('status')
        if incident_status:
            valid = dict(Incident.STATUS_CHOICES)
            if incident_status not in valid:
                return Response(
                    {'detail': f'Invalid status. Choose one of: {", ".join(valid)}.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(status=incident_status)
        elif request.query_params.get('resolved', '').lower() != 'true':
            # Default view is "what's broken right now".
            qs = qs.filter(resolved_at__isnull=True)

        # ?monitor=<id>
        monitor_id = request.query_params.get('monitor')
        if monitor_id:
            if not monitor_id.isdigit():
                return Response(
                    {'detail': 'monitor must be a numeric id.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(monitor_id=int(monitor_id))

        serializer = IncidentSerializer(qs.order_by('-started_at'), many=True)
        return Response(serializer.data)


class IncidentDetailView(APIView):
    """
    GET   /api/v1/orgs/{orgId}/incidents/{incidentId}/
    POST  /api/v1/orgs/{orgId}/incidents/{incidentId}/updates/  — Post status update
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def _get_incident(self, org, incident_id):
        try:
            return Incident.objects.get(pk=incident_id, organization=org)
        except Incident.DoesNotExist:
            return None

    def get(self, request, orgId, incidentId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        incident = self._get_incident(org, incidentId)
        if not incident:
            return Response({'detail': 'Incident not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(IncidentSerializer(incident).data)


class IncidentUpdateView(APIView):
    """
    POST /api/v1/orgs/{orgId}/incidents/{incidentId}/updates/
    Post a new status update to an incident.
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def post(self, request, orgId, incidentId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            incident = Incident.objects.get(pk=incidentId, organization=org)
        except Incident.DoesNotExist:
            return Response({'detail': 'Incident not found.'}, status=status.HTTP_404_NOT_FOUND)

        if incident.resolved_at is not None:
            return Response(
                {'detail': 'Cannot update a resolved incident.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = IncidentPostUpdateSerializer(data=request.data)
        if serializer.is_valid():
            update = IncidentUpdate.objects.create(
                incident=incident,
                posted_by=request.user,
                **serializer.validated_data,
            )
            # Also advance the incident's own status
            incident.status = serializer.validated_data['status']
            if serializer.validated_data['status'] == 'resolved':
                incident.resolved_at = timezone.now()
            incident.save(update_fields=['status', 'resolved_at'])

            return Response(
                IncidentSerializer(incident).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class IncidentResolveView(APIView):
    """
    POST /api/v1/orgs/{orgId}/incidents/{incidentId}/resolve/
    Manually close an incident. Also clears the monitor's failure counter so
    the next failed check starts a fresh run rather than instantly re-opening.
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def post(self, request, orgId, incidentId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            incident = Incident.objects.select_related('monitor').get(
                pk=incidentId, organization=org
            )
        except Incident.DoesNotExist:
            return Response({'detail': 'Incident not found.'}, status=status.HTTP_404_NOT_FOUND)

        if incident.resolved_at is not None:
            return Response(
                {'detail': 'Incident is already resolved.'},
                status=status.HTTP_409_CONFLICT,
            )

        message = request.data.get('message') or 'Manually marked resolved.'
        now = timezone.now()

        with transaction.atomic():
            incident.status = 'resolved'
            incident.resolved_at = now
            incident.save(update_fields=['status', 'resolved_at'])

            IncidentUpdate.objects.create(
                incident=incident,
                status='resolved',
                message=message,
                posted_by=request.user,
            )

            monitor = Monitor.objects.select_for_update().get(pk=incident.monitor_id)
            monitor.last_status = 'up'
            monitor.consecutive_failures = 0
            monitor.save(update_fields=['last_status', 'consecutive_failures', 'updated_at'])

        notify_incident(incident.pk, 'resolved')
        return Response(IncidentSerializer(incident).data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Status Pages (private management)
# ---------------------------------------------------------------------------

class StatusPageListCreateView(APIView):
    """
    GET  /api/v1/orgs/{orgId}/status-pages/  — List the org's status pages
    POST /api/v1/orgs/{orgId}/status-pages/  — Create one
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def get(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)

        pages = StatusPage.objects.filter(organization=org).prefetch_related(
            'page_monitors__monitor', 'subscribers'
        )
        return Response(StatusPageSerializer(pages, many=True).data)

    def post(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = StatusPageWriteSerializer(
            data=request.data, context={'request': request, 'organization': org}
        )
        if serializer.is_valid():
            page = serializer.save()
            return Response(StatusPageSerializer(page).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class StatusPageDetailView(APIView):
    """
    GET    /api/v1/orgs/{orgId}/status-pages/{pageId}/
    PATCH  /api/v1/orgs/{orgId}/status-pages/{pageId}/  — settings + monitor list
    DELETE /api/v1/orgs/{orgId}/status-pages/{pageId}/  — admin only
    """

    def get_permissions(self):
        if self.request.method == 'DELETE':
            return [IsAuthenticated(), IsOrgAdmin()]
        return [IsAuthenticated(), IsOrgMember()]

    def _get(self, org, page_id):
        try:
            return StatusPage.objects.get(pk=page_id, organization=org)
        except StatusPage.DoesNotExist:
            return None

    def get(self, request, orgId, pageId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        page = self._get(org, pageId)
        if not page:
            return Response({'detail': 'Status page not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(StatusPageSerializer(page).data)

    def patch(self, request, orgId, pageId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        page = self._get(org, pageId)
        if not page:
            return Response({'detail': 'Status page not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = StatusPageWriteSerializer(
            page, data=request.data, partial=True,
            context={'request': request, 'organization': org},
        )
        if serializer.is_valid():
            updated = serializer.save()
            return Response(StatusPageSerializer(updated).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, orgId, pageId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        page = self._get(org, pageId)
        if not page:
            return Response({'detail': 'Status page not found.'}, status=status.HTTP_404_NOT_FOUND)
        page.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Public status page (no auth)
# ---------------------------------------------------------------------------

PUBLIC_UPTIME_DAYS = 30


class PublicStatusPageView(APIView):
    """
    GET /api/v1/public/status-pages/{slug}/

    Everything a status widget needs in one request: per-monitor current state,
    a 30-day daily uptime series for the bars, and any open incidents.
    Nothing here is org-scoped output — only what the page owner marked public.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        try:
            page = StatusPage.objects.get(slug=slug, is_public=True)
        except StatusPage.DoesNotExist:
            return Response({'detail': 'Status page not found.'}, status=status.HTTP_404_NOT_FOUND)

        if not _page_password_ok(page, request):
            # 401 with the flag set so the frontend knows to show a prompt
            # rather than a generic error.
            return Response(
                {'detail': 'This status page is password protected.',
                 'password_required': True},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        entries = page.page_monitors.select_related('monitor').filter(
            monitor__deleted_at__isnull=True
        )
        monitors = [e.monitor for e in entries]

        since = timezone.now() - timedelta(days=PUBLIC_UPTIME_DAYS)
        monitor_payload = [
            {
                'id': m.id,
                'name': m.name,
                'status': m.last_status,
                'uptime_30d': _uptime_pct(m, since),
                'daily': _daily_uptime(m, PUBLIC_UPTIME_DAYS),
            }
            for m in monitors
        ]

        incidents = Incident.objects.filter(
            monitor__in=monitors, resolved_at__isnull=True
        ).select_related('monitor').prefetch_related('updates').order_by('-started_at')

        # Worst monitor state wins for the page-level banner.
        if any(m.last_status == 'down' for m in monitors):
            overall = 'major_outage'
        elif any(m.last_status == 'degraded' for m in monitors):
            overall = 'degraded'
        else:
            overall = 'operational'

        return Response({
            'slug': page.slug,
            'title': page.title,
            'theme': page.theme,
            'status': overall,
            'monitors': monitor_payload,
            'active_incidents': PublicIncidentSerializer(incidents, many=True).data,
            # Readers want the track record, not just "is it broken right now".
            'incident_history': PublicIncidentSerializer(
                Incident.objects.filter(
                    monitor__in=monitors, resolved_at__isnull=False,
                ).select_related('monitor').prefetch_related('updates')
                .order_by('-started_at')[:20],
                many=True,
            ).data,
            # Planned work, so scheduled downtime doesn't read as an outage.
            'maintenance': [
                {
                    'id': w.pk,
                    'title': w.title,
                    'description': w.description,
                    'starts_at': w.starts_at,
                    'ends_at': w.ends_at,
                    'state': w.state,
                }
                for w in MaintenanceWindow.objects.filter(
                    organization=page.organization,
                    ends_at__gte=timezone.now() - timedelta(days=1),
                ).order_by('starts_at')[:10]
            ],
            'updated_at': timezone.now(),
        })


def _uptime_pct(monitor, since):
    logs = ApiLog.objects.filter(monitor=monitor, checked_at__gte=since)
    total = logs.count()
    if not total:
        return 100.0
    failed = logs.filter(result='failure').count()
    return round((total - failed) / total * 100, 4)


def _daily_uptime(monitor, days):
    """One bucket per day, oldest first — the classic status-page bar strip."""
    since = timezone.now() - timedelta(days=days)
    rows = (
        ApiLog.objects
        .filter(monitor=monitor, checked_at__gte=since)
        .annotate(day=TruncDate('checked_at'))
        .values('day')
        .annotate(
            total=Count('id'),
            failed=Count('id', filter=Q(result='failure')),
        )
        .order_by('day')
    )
    return [
        {
            'date': r['day'],
            'uptime_pct': round((r['total'] - r['failed']) / r['total'] * 100, 4),
            'checks': r['total'],
        }
        for r in rows
    ]


class PublicSubscribeView(APIView):
    """
    POST /api/v1/public/status-pages/{slug}/subscribe/

    Rate-limited per IP. Always answers the same way whether or not the address
    was already subscribed, so this endpoint can't be used to enumerate who
    watches a page.
    """
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'subscribe'

    def post(self, request, slug):
        try:
            page = StatusPage.objects.get(slug=slug, is_public=True)
        except StatusPage.DoesNotExist:
            return Response({'detail': 'Status page not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SubscribeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data['email']
        subscriber, created = Subscriber.objects.get_or_create(
            status_page=page, email=email,
            defaults={
                'verification_token': secrets.token_urlsafe(32),
                'unsubscribe_token': secrets.token_urlsafe(32),
            },
        )
        if not created and not subscriber.verified:
            # Re-sending: rotate the token so old links stop working.
            subscriber.verification_token = secrets.token_urlsafe(32)
            subscriber.save(update_fields=['verification_token'])

        if not subscriber.verified:
            verify_url = request.build_absolute_uri(
                f'/api/v1/public/status-pages/{page.slug}/verify/{subscriber.verification_token}/'
            )
            # Email delivery is an explicit non-goal for v1 — log the link so
            # the flow is exercisable end to end.
            logger.info('Verification link for %s: %s', email, verify_url)

        return Response(
            {'detail': 'If that address is valid, a verification link has been sent.'},
            status=status.HTTP_202_ACCEPTED,
        )


class PublicVerifyView(APIView):
    """GET /api/v1/public/status-pages/{slug}/verify/{token}/"""
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, slug, token):
        try:
            subscriber = Subscriber.objects.get(
                status_page__slug=slug, verification_token=token
            )
        except Subscriber.DoesNotExist:
            return Response(
                {'detail': 'Invalid or expired verification link.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not subscriber.verified:
            subscriber.verified = True
            # Burn the token so the link is single-use.
            subscriber.verification_token = ''
            subscriber.save(update_fields=['verified', 'verification_token'])

        return Response({'detail': 'Subscription confirmed.', 'email': subscriber.email})


# ---------------------------------------------------------------------------
# Alert Channels  (Phase 4)
# ---------------------------------------------------------------------------

class AlertChannelListCreateView(APIView):
    """
    GET  /api/v1/orgs/{orgId}/alert-channels/  — member
    POST /api/v1/orgs/{orgId}/alert-channels/  — admin only (holds a secret URL)
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsOrgAdmin()]
        return [IsAuthenticated(), IsOrgMember()]

    def get(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        channels = AlertChannel.objects.filter(organization=org)
        return Response(AlertChannelSerializer(channels, many=True).data)

    def post(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AlertChannelWriteSerializer(
            data=request.data, context={'organization': org}
        )
        if serializer.is_valid():
            channel = serializer.save()
            return Response(AlertChannelSerializer(channel).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AlertChannelDetailView(APIView):
    """
    PATCH  /api/v1/orgs/{orgId}/alert-channels/{channelId}/  — admin
    DELETE /api/v1/orgs/{orgId}/alert-channels/{channelId}/  — admin
    """
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def _get(self, org, channel_id):
        try:
            return AlertChannel.objects.get(pk=channel_id, organization=org)
        except AlertChannel.DoesNotExist:
            return None

    def patch(self, request, orgId, channelId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        channel = self._get(org, channelId)
        if not channel:
            return Response({'detail': 'Alert channel not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AlertChannelWriteSerializer(
            channel, data=request.data, partial=True, context={'organization': org}
        )
        if serializer.is_valid():
            return Response(AlertChannelSerializer(serializer.save()).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, orgId, channelId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        channel = self._get(org, channelId)
        if not channel:
            return Response({'detail': 'Alert channel not found.'}, status=status.HTTP_404_NOT_FOUND)
        channel.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AlertChannelTestView(APIView):
    """
    POST /api/v1/orgs/{orgId}/alert-channels/{channelId}/test/
    Sends a real message and reports whether the destination accepted it.
    """
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def post(self, request, orgId, channelId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            channel = AlertChannel.objects.get(pk=channelId, organization=org)
        except AlertChannel.DoesNotExist:
            return Response({'detail': 'Alert channel not found.'}, status=status.HTTP_404_NOT_FOUND)

        result, error = send_test_message(channel)
        if result == 'sent':
            return Response({'success': True, 'detail': 'Test message delivered.'})
        return Response(
            {'success': False, 'status': result, 'detail': error},
            status=status.HTTP_502_BAD_GATEWAY,
        )


# ---------------------------------------------------------------------------
# API Tokens
# ---------------------------------------------------------------------------

class ApiTokenListCreateView(APIView):
    """
    GET  /api/v1/orgs/{orgId}/tokens/  — member; masked, never the full token
    POST /api/v1/orgs/{orgId}/tokens/  — admin; returns plaintext exactly once
    """

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsOrgAdmin()]
        return [IsAuthenticated(), IsOrgMember()]

    def get(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        tokens = ApiToken.objects.filter(organization=org).select_related('user')
        return Response(ApiTokenSerializer(tokens, many=True).data)

    def post(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ApiTokenCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        plaintext, token_hash, prefix = generate_token()
        expires_in = serializer.validated_data.get('expires_in_days')

        token = ApiToken.objects.create(
            user=request.user,
            organization=org,
            name=serializer.validated_data['name'],
            token_hash=token_hash,
            prefix=prefix,
            expires_at=timezone.now() + timedelta(days=expires_in) if expires_in else None,
        )

        data = ApiTokenSerializer(token).data
        # The only time the plaintext ever leaves this process.
        data['token'] = plaintext
        data['warning'] = 'Store this token now — it cannot be retrieved again.'
        return Response(data, status=status.HTTP_201_CREATED)


class ApiTokenDetailView(APIView):
    """DELETE /api/v1/orgs/{orgId}/tokens/{tokenId}/  — revoke (admin)."""
    permission_classes = [IsAuthenticated, IsOrgAdmin]

    def delete(self, request, orgId, tokenId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            token = ApiToken.objects.get(pk=tokenId, organization=org)
        except ApiToken.DoesNotExist:
            return Response({'detail': 'Token not found.'}, status=status.HTTP_404_NOT_FOUND)
        token.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Server-Sent Events (real-time dashboard updates)
# ---------------------------------------------------------------------------

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def monitor_events(request, orgId):
    """
    GET /api/v1/orgs/{orgId}/events/?token=<access-token>

    Live monitor state changes for one organization, as Server-Sent Events.

    The browser's EventSource cannot set an Authorization header, so the access
    token comes in the query string and is validated here by hand. That is
    acceptable only because access tokens are short-lived (15 min); it is still
    a URL, so it can land in proxy logs. Refresh tokens must never be used here.
    """
    token = request.query_params.get('token')
    if not token:
        return Response(
            {'detail': 'A "token" query parameter is required.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        validated = JWTAuthentication().get_validated_token(token)
        user = JWTAuthentication().get_user(validated)
    except (InvalidToken, TokenError, AuthenticationFailed):
        return Response({'detail': 'Invalid or expired token.'}, status=status.HTTP_401_UNAUTHORIZED)

    if not OrganizationMember.objects.filter(users=user, organizations_id=orgId).exists():
        return Response(
            {'detail': 'You are not a member of this organization.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    response = StreamingHttpResponse(
        event_stream(int(orgId)),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'  # tell nginx not to buffer the stream
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def apprise_schemas(request):
    """
    GET /api/v1/alert-channels/schemas/

    Every notification schema this install supports, so the UI can offer a
    picker instead of making the user guess the URL format.
    """
    from .apprise_channel import available_schemas

    schemas = available_schemas()
    return Response({
        'count': len(schemas),
        'schemas': schemas,
        'examples': {
            'telegram': 'tgram://bottoken/ChatID',
            'discord': 'discord://webhook_id/webhook_token',
            'slack': 'slack://TokenA/TokenB/TokenC/Channel',
            'ntfy': 'ntfy://topic',
            'gotify': 'gotify://hostname/token',
            'matrix': 'matrix://user:pass@hostname/#room',
            'email': 'mailto://user:pass@gmail.com',
            'msteams': 'msteams://TokenA/TokenB/TokenC/',
            'pushover': 'pover://user_key@token',
        },
    })


@api_view(['GET', 'POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def heartbeat_ping(request, token):
    """
    GET|POST /api/v1/heartbeat/{token}/

    The push half of heartbeat monitoring: a cron job, backup script or worker
    calls this on every successful run. If the calls stop, the monitor goes
    down — which is the only way to detect a job that silently stopped running.

    Unauthenticated by design: the token IS the credential, and it has to be
    callable from a bare `curl` at the end of a shell script. It reveals
    nothing and can only mark a monitor healthy.
    """
    now = timezone.now()
    updated = Monitor.objects.filter(
        heartbeat_token=token, type='heartbeat', deleted_at__isnull=True,
    ).update(last_heartbeat_at=now, last_checked_at=now)

    if not updated:
        return Response({'detail': 'Unknown heartbeat token.'},
                        status=status.HTTP_404_NOT_FOUND)

    monitor = Monitor.objects.filter(heartbeat_token=token).first()

    # Recovery is immediate, unlike the 5-consecutive-success rule used for
    # polled checks. That rule exists to stop a flapping endpoint opening and
    # closing incidents; a heartbeat is different — the job just told us it
    # ran, which is proof of life. Requiring five pings would leave an hourly
    # job showing "down" for five hours after it recovered.
    if monitor.last_status != 'up':
        was_down = monitor.last_status == 'down'
        monitor.last_status = 'up'
        monitor.consecutive_failures = 0
        monitor.save(update_fields=['last_status', 'consecutive_failures', 'updated_at'])
        if was_down:
            auto_resolve_incident(monitor)
            logger.info('Heartbeat monitor %s recovered.', monitor.pk)
    elif monitor.consecutive_failures != 0:
        monitor.consecutive_failures = 0
        monitor.save(update_fields=['consecutive_failures', 'updated_at'])

    return Response({'detail': 'Heartbeat received.', 'monitor': monitor.name})


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

def _prom_escape(value: str) -> str:
    """Escape a Prometheus label value."""
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def prometheus_metrics(request):
    """
    GET /api/v1/metrics

    Prometheus text exposition. Authenticated — the metric labels carry monitor
    names and URLs, so this is org data, not a public endpoint. Prometheus
    supports bearer tokens and our API tokens work here:

        - job_name: vectotrace
          authorization:
            type: Bearer
            credentials: vtk_...
          static_configs: [{targets: ['vectotrace:8000']}]
          metrics_path: /api/v1/metrics

    Scoped to organizations the caller belongs to, exactly like every other
    endpoint — a scrape token cannot see another tenant's monitors.
    """
    org_ids = OrganizationMember.objects.filter(
        users=request.user
    ).values_list('organizations_id', flat=True)

    monitors = Monitor.objects.filter(
        organization_id__in=org_ids, deleted_at__isnull=True,
    ).select_related('organization')

    # 0/1 gauges rather than a status label, because that is what alerting
    # rules want: `vectotrace_monitor_up == 0`.
    status_value = {'up': 1, 'degraded': 1, 'down': 0}

    lines = [
        '# HELP vectotrace_monitor_up Whether the monitor is currently reachable (1 = up).',
        '# TYPE vectotrace_monitor_up gauge',
    ]
    degraded_lines = [
        '# HELP vectotrace_monitor_degraded Whether the monitor is up but slow (1 = degraded).',
        '# TYPE vectotrace_monitor_degraded gauge',
    ]
    rt_lines = [
        '# HELP vectotrace_monitor_response_time_ms Most recent response time in milliseconds.',
        '# TYPE vectotrace_monitor_response_time_ms gauge',
    ]
    cert_lines = [
        '# HELP vectotrace_monitor_cert_expiry_days Days until the TLS certificate expires.',
        '# TYPE vectotrace_monitor_cert_expiry_days gauge',
    ]

    now = timezone.now()
    latest = {
        row['monitor_id']: row
        for row in ApiLog.objects.filter(
            monitor__in=monitors, checked_at__gte=now - timedelta(hours=6),
        ).order_by('monitor_id', '-checked_at')
        .distinct('monitor_id')
        .values('monitor_id', 'response_time_ms', 'ssl_expires_at')
    }

    for m in monitors:
        labels = (
            f'id="{m.pk}",'
            f'name="{_prom_escape(m.name)}",'
            f'type="{m.type}",'
            f'org="{_prom_escape(m.organization.name)}"'
        )
        lines.append(f'vectotrace_monitor_up{{{labels}}} {status_value.get(m.last_status, 0)}')
        degraded_lines.append(
            f'vectotrace_monitor_degraded{{{labels}}} {1 if m.last_status == "degraded" else 0}'
        )

        row = latest.get(m.pk)
        if row and row['response_time_ms'] is not None:
            rt_lines.append(
                f'vectotrace_monitor_response_time_ms{{{labels}}} {row["response_time_ms"]}'
            )
        if row and row['ssl_expires_at']:
            days = (row['ssl_expires_at'] - now).days
            cert_lines.append(f'vectotrace_monitor_cert_expiry_days{{{labels}}} {days}')

    body = '\n'.join(lines + degraded_lines + rt_lines + cert_lines) + '\n'
    return HttpResponse(body, content_type='text/plain; version=0.0.4; charset=utf-8')


# ---------------------------------------------------------------------------
# Status page extras (Phase D)
# ---------------------------------------------------------------------------

def _page_or_404(slug):
    try:
        return StatusPage.objects.get(slug=slug, is_public=True)
    except StatusPage.DoesNotExist:
        return None


def _page_password_ok(page, request) -> bool:
    """Password may arrive as a header (widgets) or a query param (browsers)."""
    if not page.is_password_protected:
        return True
    supplied = request.headers.get('X-Page-Password') or request.query_params.get('password')
    return page.check_password(supplied)


class PublicUnsubscribeView(APIView):
    """
    GET|POST /api/v1/public/unsubscribe/{token}/

    One click, no login, no confirmation step. Every notification carries this
    link — making it hard to leave is how a status page ends up marked as spam.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, token):
        return self._remove(token)

    def post(self, request, token):
        return self._remove(token)

    def _remove(self, token):
        subscriber = Subscriber.objects.filter(unsubscribe_token=token).first()
        if not subscriber:
            # Same answer whether or not the token existed — an unsubscribe
            # endpoint shouldn't confirm who is subscribed.
            return Response({'detail': 'You have been unsubscribed.'})
        email = subscriber.email
        subscriber.delete()
        logger.info('Unsubscribed %s', email)
        return Response({'detail': 'You have been unsubscribed.'})


class StatusPageSubscriberListView(APIView):
    """
    GET    /api/v1/orgs/{orgId}/status-pages/{pageId}/subscribers/
    DELETE /api/v1/orgs/{orgId}/status-pages/{pageId}/subscribers/{subId}/
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def get(self, request, orgId, pageId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            page = StatusPage.objects.get(pk=pageId, organization=org)
        except StatusPage.DoesNotExist:
            return Response({'detail': 'Status page not found.'}, status=status.HTTP_404_NOT_FOUND)

        subs = Subscriber.objects.filter(status_page=page).order_by('-subscribed_at')
        return Response([
            {
                'id': s.pk,
                'email': s.email,
                'webhook_url': s.webhook_url,
                'verified': s.verified,
                'subscribed_at': s.subscribed_at,
            }
            for s in subs
        ])

    def delete(self, request, orgId, pageId, subId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        deleted, _ = Subscriber.objects.filter(
            pk=subId, status_page__pk=pageId, status_page__organization=org,
        ).delete()
        if not deleted:
            return Response({'detail': 'Subscriber not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PublicStatusFeedView(APIView):
    """
    GET /api/v1/public/status-pages/{slug}/feed/

    RSS 2.0 of incidents. Readers subscribe in a feed reader instead of by
    email, which costs us nothing to deliver.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        page = _page_or_404(slug)
        if not page:
            return Response({'detail': 'Status page not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not _page_password_ok(page, request):
            return Response({'detail': 'Password required.'}, status=status.HTTP_401_UNAUTHORIZED)

        monitors = Monitor.objects.filter(status_page_entries__status_page=page)
        incidents = Incident.objects.filter(
            monitor__in=monitors
        ).select_related('monitor').order_by('-started_at')[:50]

        page_url = request.build_absolute_uri(f'/status/{page.slug}')
        items = []
        for inc in incidents:
            state = 'Resolved' if inc.resolved_at else inc.status.title()
            # escape() everything: incident titles and update text are
            # user-authored and must not be able to inject XML.
            items.append(
                '<item>'
                f'<title>[{escape(state)}] {escape(inc.title)}</title>'
                f'<description>{escape(inc.monitor.name)} — severity {escape(inc.severity)}</description>'
                f'<link>{escape(page_url)}</link>'
                f'<guid isPermaLink="false">incident-{inc.pk}</guid>'
                f'<pubDate>{http_date(inc.started_at.timestamp())}</pubDate>'
                '</item>'
            )

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<rss version="2.0"><channel>'
            f'<title>{escape(page.title)}</title>'
            f'<link>{escape(page_url)}</link>'
            f'<description>Incident history for {escape(page.title)}</description>'
            + ''.join(items) +
            '</channel></rss>'
        )
        return HttpResponse(xml, content_type='application/rss+xml; charset=utf-8')


class PublicStatusBadgeView(APIView):
    """
    GET /api/v1/public/status-pages/{slug}/badge.svg

    An SVG badge for READMEs and docs sites. Deliberately dependency-free and
    cacheable for a minute so embedding it can't be used to hammer us.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    COLOURS = {
        'operational': '#3fb950',
        'degraded': '#d29922',
        'major_outage': '#f85149',
        'unknown': '#8b949e',
    }
    LABELS = {
        'operational': 'operational',
        'degraded': 'degraded',
        'major_outage': 'major outage',
        'unknown': 'unknown',
    }

    def get(self, request, slug):
        page = _page_or_404(slug)
        if not page:
            state = 'unknown'
        else:
            monitors = [e.monitor for e in page.page_monitors.select_related('monitor')
                        .filter(monitor__deleted_at__isnull=True)]
            if not monitors:
                state = 'unknown'
            elif any(m.last_status == 'down' for m in monitors):
                state = 'major_outage'
            elif any(m.last_status == 'degraded' for m in monitors):
                state = 'degraded'
            else:
                state = 'operational'

        label, value = 'status', self.LABELS[state]
        colour = self.COLOURS[state]
        # ~6.5px per character at 11px monospace-ish; close enough for a badge.
        lw, vw = 6 * len(label) + 10, 6 * len(value) + 10
        total = lw + vw

        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{label}: {value}">
<title>{label}: {value}</title>
<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient>
<clipPath id="r"><rect width="{total}" height="20" rx="3" fill="#fff"/></clipPath>
<g clip-path="url(#r)">
<rect width="{lw}" height="20" fill="#555"/>
<rect x="{lw}" width="{vw}" height="20" fill="{colour}"/>
<rect width="{total}" height="20" fill="url(#s)"/>
</g>
<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">
<text x="{lw / 2}" y="14">{label}</text>
<text x="{lw + vw / 2}" y="14">{value}</text>
</g>
</svg>'''
        resp = HttpResponse(svg, content_type='image/svg+xml')
        resp['Cache-Control'] = 'max-age=60, public'
        return resp


class MaintenanceWindowListCreateView(APIView):
    """
    GET  /api/v1/orgs/{orgId}/maintenance/
    POST /api/v1/orgs/{orgId}/maintenance/
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def get(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        windows = MaintenanceWindow.objects.filter(organization=org).prefetch_related('monitors')
        return Response(MaintenanceWindowSerializer(windows, many=True).data)

    def post(self, request, orgId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = MaintenanceWindowWriteSerializer(
            data=request.data, context={'request': request, 'organization': org},
        )
        if serializer.is_valid():
            window = serializer.save()
            return Response(MaintenanceWindowSerializer(window).data,
                            status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MaintenanceWindowDetailView(APIView):
    """
    PATCH  /api/v1/orgs/{orgId}/maintenance/{windowId}/
    DELETE /api/v1/orgs/{orgId}/maintenance/{windowId}/
    """
    permission_classes = [IsAuthenticated, IsOrgMember]

    def _get(self, org, window_id):
        return MaintenanceWindow.objects.filter(pk=window_id, organization=org).first()

    def patch(self, request, orgId, windowId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        window = self._get(org, windowId)
        if not window:
            return Response({'detail': 'Maintenance window not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        serializer = MaintenanceWindowWriteSerializer(
            window, data=request.data, partial=True,
            context={'request': request, 'organization': org},
        )
        if serializer.is_valid():
            return Response(MaintenanceWindowSerializer(serializer.save()).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, orgId, windowId):
        org = _get_org_or_404(orgId)
        if not org:
            return Response({'detail': 'Organization not found.'}, status=status.HTTP_404_NOT_FOUND)
        window = self._get(org, windowId)
        if not window:
            return Response({'detail': 'Maintenance window not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        window.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
