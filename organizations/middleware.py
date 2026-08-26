import re
from django.http import JsonResponse
from .models import Organization


# Matches /api/v1/organizations/123/... (the org resource itself) and
# /api/v1/orgs/123/... (everything nested under an org: monitors, incidents, …)
_ORG_PATH_RE = re.compile(r'^/api/v\d+/(?:organizations|orgs)/(?P<orgId>\d+)')


class OrganizationMiddleware:
    """
    Multi-tenant middleware that resolves the organization from the URL path
    and attaches it to the request as `request.organization`.

    Only activates for paths matching /api/v*/organizations/<orgId>/...
    If the orgId is present but the organization does not exist, returns 404.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        match = _ORG_PATH_RE.search(request.path)
        if match:
            org_id = match.group('orgId')
            try:
                request.organization = Organization.objects.get(pk=org_id)
            except Organization.DoesNotExist:
                return JsonResponse(
                    {'detail': 'Organization not found.'},
                    status=404,
                )
        else:
            request.organization = None

        return self.get_response(request)
