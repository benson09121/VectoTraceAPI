from django.urls import path
from .views import (
    MonitorListCreateView,
    MonitorDetailView,
    MonitorPauseView,
    MonitorResumeView,
    MonitorChecksView,
    MonitorUptimeView,
    IncidentListView,
    IncidentDetailView,
    IncidentUpdateView,
    IncidentResolveView,
    StatusPageListCreateView,
    StatusPageDetailView,
    PublicStatusPageView,
    PublicSubscribeView,
    PublicVerifyView,
    AlertChannelListCreateView,
    AlertChannelDetailView,
    AlertChannelTestView,
    ApiTokenListCreateView,
    ApiTokenDetailView,
    monitor_events,
    apprise_schemas,
    heartbeat_ping,
    prometheus_metrics,
    PublicUnsubscribeView,
    PublicStatusFeedView,
    PublicStatusBadgeView,
    StatusPageSubscriberListView,
    MaintenanceWindowListCreateView,
    MaintenanceWindowDetailView,
)

urlpatterns = [
    # Monitor CRUD
    path(
        'orgs/<int:orgId>/monitors/',
        MonitorListCreateView.as_view(),
        name='monitor-list-create',
    ),
    path(
        'orgs/<int:orgId>/monitors/<int:monitorId>/',
        MonitorDetailView.as_view(),
        name='monitor-detail',
    ),
    # Pause / Resume
    path(
        'orgs/<int:orgId>/monitors/<int:monitorId>/pause/',
        MonitorPauseView.as_view(),
        name='monitor-pause',
    ),
    path(
        'orgs/<int:orgId>/monitors/<int:monitorId>/resume/',
        MonitorResumeView.as_view(),
        name='monitor-resume',
    ),
    # Check history (paginated)
    path(
        'orgs/<int:orgId>/monitors/<int:monitorId>/checks/',
        MonitorChecksView.as_view(),
        name='monitor-checks',
    ),
    # Uptime stats
    path(
        'orgs/<int:orgId>/monitors/<int:monitorId>/uptime/',
        MonitorUptimeView.as_view(),
        name='monitor-uptime',
    ),
    # Incidents
    path(
        'orgs/<int:orgId>/incidents/',
        IncidentListView.as_view(),
        name='incident-list',
    ),
    path(
        'orgs/<int:orgId>/incidents/<int:incidentId>/',
        IncidentDetailView.as_view(),
        name='incident-detail',
    ),
    path(
        'orgs/<int:orgId>/incidents/<int:incidentId>/updates/',
        IncidentUpdateView.as_view(),
        name='incident-update',
    ),
    path(
        'orgs/<int:orgId>/incidents/<int:incidentId>/resolve/',
        IncidentResolveView.as_view(),
        name='incident-resolve',
    ),
    # Status pages (private management)
    path(
        'orgs/<int:orgId>/status-pages/',
        StatusPageListCreateView.as_view(),
        name='status-page-list-create',
    ),
    path(
        'orgs/<int:orgId>/status-pages/<int:pageId>/',
        StatusPageDetailView.as_view(),
        name='status-page-detail',
    ),

    # Public (no auth)
    path(
        'public/status-pages/<slug:slug>/',
        PublicStatusPageView.as_view(),
        name='public-status-page',
    ),
    path(
        'public/status-pages/<slug:slug>/subscribe/',
        PublicSubscribeView.as_view(),
        name='public-subscribe',
    ),
    path(
        'public/status-pages/<slug:slug>/verify/<str:token>/',
        PublicVerifyView.as_view(),
        name='public-verify',
    ),

    # Alert channels
    path(
        'orgs/<int:orgId>/alert-channels/',
        AlertChannelListCreateView.as_view(),
        name='alert-channel-list-create',
    ),
    path(
        'orgs/<int:orgId>/alert-channels/<int:channelId>/',
        AlertChannelDetailView.as_view(),
        name='alert-channel-detail',
    ),
    path(
        'orgs/<int:orgId>/alert-channels/<int:channelId>/test/',
        AlertChannelTestView.as_view(),
        name='alert-channel-test',
    ),

    # API tokens
    path(
        'orgs/<int:orgId>/tokens/',
        ApiTokenListCreateView.as_view(),
        name='api-token-list-create',
    ),
    path(
        'orgs/<int:orgId>/tokens/<int:tokenId>/',
        ApiTokenDetailView.as_view(),
        name='api-token-detail',
    ),

    # Real-time events (SSE)
    path(
        'orgs/<int:orgId>/events/',
        monitor_events,
        name='monitor-events',
    ),

    # Supported notification schemas (for the channel picker)
    path(
        'alert-channels/schemas/',
        apprise_schemas,
        name='apprise-schemas',
    ),

    # Heartbeat push endpoint — the job calls this, we alert when it stops.
    path(
        'heartbeat/<str:token>/',
        heartbeat_ping,
        name='heartbeat-ping',
    ),

    # Prometheus scrape endpoint (authenticated — labels carry org data).
    path(
        'metrics',
        prometheus_metrics,
        name='prometheus-metrics',
    ),

    # --- Phase D: status page extras ---
    path(
        'public/unsubscribe/<str:token>/',
        PublicUnsubscribeView.as_view(),
        name='public-unsubscribe',
    ),
    path(
        'public/status-pages/<slug:slug>/feed/',
        PublicStatusFeedView.as_view(),
        name='public-status-feed',
    ),
    path(
        'public/status-pages/<slug:slug>/badge.svg',
        PublicStatusBadgeView.as_view(),
        name='public-status-badge',
    ),
    path(
        'orgs/<int:orgId>/status-pages/<int:pageId>/subscribers/',
        StatusPageSubscriberListView.as_view(),
        name='status-page-subscribers',
    ),
    path(
        'orgs/<int:orgId>/status-pages/<int:pageId>/subscribers/<int:subId>/',
        StatusPageSubscriberListView.as_view(),
        name='status-page-subscriber-delete',
    ),

    # --- Maintenance windows ---
    path(
        'orgs/<int:orgId>/maintenance/',
        MaintenanceWindowListCreateView.as_view(),
        name='maintenance-list-create',
    ),
    path(
        'orgs/<int:orgId>/maintenance/<int:windowId>/',
        MaintenanceWindowDetailView.as_view(),
        name='maintenance-detail',
    ),
]
