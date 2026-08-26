import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from surveillance.alerts import build_payload, _TestIncident

class MockChannel:
    type = 'slack'
    config = {
        'custom_message': 'Hey team, [#service_name#] is currently [#status#]! URL: [#url#] (Type: [#type#]). Severity: [#severity#], Event: [#event#]. Title: [#title#]'
    }

channel = MockChannel()
incident = _TestIncident()

payload = build_payload(channel, incident, 'opened')
print("--- CUSTOM MESSAGE PAYLOAD ---")
print(payload['text'])
print("------------------------------")
