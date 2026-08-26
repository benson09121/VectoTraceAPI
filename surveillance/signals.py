import json
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import AuditLog, Monitor, ProbeToken, AlertChannel
from organizations.models import Organization

# NOTE: For MVP, we are not extracting the actor (user) since signals don't have request context.
# In a real app we'd use threadlocals or middleware to inject the actor.

def log_action(instance, action, new_state=None):
    org = None
    if hasattr(instance, 'organization'):
        org = instance.organization
    
    resource_id = str(instance.pk)
    
    AuditLog.objects.create(
        organization=org,
        actor=None,
        action=action,
        resource_type=instance.__class__.__name__,
        resource_id=resource_id,
        new_state=new_state
    )

@receiver(post_save, sender=Monitor)
def monitor_saved(sender, instance, created, **kwargs):
    state = {'name': instance.name, 'type': instance.type, 'url': instance.url}
    log_action(instance, 'create' if created else 'update', state)

@receiver(post_delete, sender=Monitor)
def monitor_deleted(sender, instance, **kwargs):
    log_action(instance, 'delete')

@receiver(post_save, sender=AlertChannel)
def channel_saved(sender, instance, created, **kwargs):
    state = {'type': instance.type, 'is_enabled': instance.is_enabled}
    log_action(instance, 'create' if created else 'update', state)

@receiver(post_delete, sender=AlertChannel)
def channel_deleted(sender, instance, **kwargs):
    log_action(instance, 'delete')

@receiver(post_save, sender=ProbeToken)
def probetoken_saved(sender, instance, created, **kwargs):
    state = {'name': instance.name, 'prefix': instance.prefix}
    # ProbeToken is linked to probe -> organization
    org = instance.probe.organization
    
    AuditLog.objects.create(
        organization=org,
        actor=None,
        action='create' if created else 'update',
        resource_type='ProbeToken',
        resource_id=str(instance.pk),
        new_state=state
    )

@receiver(post_delete, sender=ProbeToken)
def probetoken_deleted(sender, instance, **kwargs):
    org = instance.probe.organization
    AuditLog.objects.create(
        organization=org,
        actor=None,
        action='delete',
        resource_type='ProbeToken',
        resource_id=str(instance.pk)
    )
