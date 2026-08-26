from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.utils import timezone
from surveillance.models import Probe, ProbeAssignment, ApiLog, Monitor
import json

def authenticate_probe(request):
    """Helper to authenticate a probe by its Bearer token."""
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Probe '):
        return None
    token_str = auth.split(' ')[1]
    # In a real implementation, we hash the token_str and lookup ProbeToken.
    # For MVP, we simulate it being authenticated as a test probe.
    probe, _ = Probe.objects.get_or_create(
        id='test-probe-123',
        defaults={'display_name': 'Test Probe', 'region': 'us-east-1'}
    )
    return probe

@api_view(['GET'])
@permission_classes([AllowAny])
def poll_assignments(request):
    probe = authenticate_probe(request)
    if not probe:
        return Response({'detail': 'Invalid probe token.'}, status=status.HTTP_401_UNAUTHORIZED)
    
    # Update last seen
    probe.last_seen_at = timezone.now()
    probe.save(update_fields=['last_seen_at'])

    # Find assignments due now that haven't been dispatched
    # Select for update to prevent concurrent probes pulling the same assignment
    now = timezone.now()
    assignments = ProbeAssignment.objects.select_for_update(skip_locked=True).filter(
        probe=probe,
        due_at__lte=now,
        dispatched_at__isnull=True
    )[:10]

    response_data = []
    for assignment in assignments:
        assignment.dispatched_at = now
        assignment.save(update_fields=['dispatched_at'])
        
        response_data.append({
            'id': assignment.id,
            'monitor': {
                'id': assignment.monitor.id,
                'name': assignment.monitor.name,
                'type': assignment.monitor.type,
                'url': assignment.monitor.url,
                'http_method': assignment.monitor.http_method,
                'timeout_ms': assignment.monitor.timeout_ms,
                'expected_status_codes': assignment.monitor.expected_status_codes,
            }
        })

    return Response({'assignments': response_data})

@api_view(['POST'])
@permission_classes([AllowAny])
def submit_result(request):
    probe = authenticate_probe(request)
    if not probe:
        return Response({'detail': 'Invalid probe token.'}, status=status.HTTP_401_UNAUTHORIZED)
    
    data = request.data
    assignment_id = data.get('assignment_id')
    
    try:
        assignment = ProbeAssignment.objects.get(id=assignment_id, probe=probe)
    except ProbeAssignment.DoesNotExist:
        return Response({'detail': 'Assignment not found.'}, status=status.HTTP_404_NOT_FOUND)
        
    if assignment.completed_at:
        return Response({'detail': 'Result already submitted.'}, status=status.HTTP_400_BAD_REQUEST)

    ApiLog.objects.create(
        monitor=assignment.monitor,
        region=data.get('region', probe.region),
        status_code=data.get('status_code'),
        response_time_ms=data.get('response_time_ms'),
        result=data.get('result', 'failure'),
        error_message=data.get('error_message')
    )
    
    assignment.completed_at = timezone.now()
    assignment.save(update_fields=['completed_at'])

    return Response({'status': 'ok'}, status=status.HTTP_201_CREATED)
