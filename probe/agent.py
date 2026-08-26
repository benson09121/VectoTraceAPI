import os
import sys
import time
import json
import logging
import requests
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

VECTOTRACE_URL = os.getenv('VECTOTRACE_URL', 'http://localhost:8000')
PROBE_TOKEN = os.getenv('PROBE_TOKEN')
PROBE_REGION = os.getenv('PROBE_REGION', 'us-east-1')

if not PROBE_TOKEN:
    logger.error("PROBE_TOKEN environment variable is required.")
    sys.exit(1)

HEADERS = {
    'Authorization': f'Probe {PROBE_TOKEN}',
    'Content-Type': 'application/json'
}

def execute_http_check(assignment):
    """Executes a basic HTTP check."""
    monitor = assignment['monitor']
    url = monitor['url']
    method = monitor.get('http_method', 'GET').upper()
    timeout = monitor.get('timeout_ms', 30000) / 1000.0

    result = {
        'assignment_id': assignment['id'],
        'region': PROBE_REGION,
        'status_code': None,
        'response_time_ms': None,
        'result': 'failure',
        'error_message': None
    }

    start_time = time.monotonic()
    try:
        res = requests.request(method, url, timeout=timeout, allow_redirects=monitor.get('follow_redirect', True))
        elapsed = int((time.monotonic() - start_time) * 1000)
        
        result['status_code'] = res.status_code
        result['response_time_ms'] = elapsed

        expected_codes = monitor.get('expected_status_codes', [200])
        if res.status_code in expected_codes:
            # Note: We aren't doing keyword matching in this MVP script, but it would go here.
            result['result'] = 'success'
        else:
            result['error_message'] = f"Unexpected status code: {res.status_code}"

    except requests.RequestException as e:
        result['error_message'] = str(e)

    return result

def poll_assignments():
    """Long-polls the VectoTrace API for new assignments."""
    url = f"{VECTOTRACE_URL}/api/v1/probes/assignments/poll/"
    logger.info(f"Polling {url}...")
    try:
        res = requests.get(url, headers=HEADERS, timeout=60)
        if res.status_code == 200:
            return res.json().get('assignments', [])
        elif res.status_code == 401:
            logger.error("Unauthorized: Invalid PROBE_TOKEN.")
            time.sleep(30)
        else:
            logger.warning(f"Unexpected API response: {res.status_code}")
    except requests.RequestException as e:
        logger.warning(f"Failed to reach API: {e}")
    
    return []

def submit_result(result):
    """Submits the check result back to the API."""
    url = f"{VECTOTRACE_URL}/api/v1/probes/results/"
    try:
        res = requests.post(url, headers=HEADERS, json=result, timeout=10)
        if res.status_code not in (200, 201):
            logger.error(f"Failed to submit result: {res.status_code} {res.text}")
    except requests.RequestException as e:
        logger.error(f"Error submitting result: {e}")

def execute_script_check(assignment):
    """Executes a custom python script."""
    monitor = assignment['monitor']
    script = monitor.get('script_content', '')
    
    result = {
        'assignment_id': assignment['id'],
        'region': PROBE_REGION,
        'status_code': 200,
        'response_time_ms': 0,
        'result': 'failure',
        'error_message': None
    }
    
    start_time = time.monotonic()
    try:
        # Warning: exec is dangerous if not strictly controlled. 
        # For this MVP probe agent, it executes scripts defined by the central API.
        local_scope = {}
        exec(script, {"requests": requests}, local_scope)
        if local_scope.get("success", False):
            result['result'] = 'success'
        else:
            result['error_message'] = local_scope.get("error", "Script failed without specific error.")
    except Exception as e:
        result['error_message'] = str(e)
        
    result['response_time_ms'] = int((time.monotonic() - start_time) * 1000)
    return result

def main():
    logger.info(f"VectoTrace Probe Agent starting up in region {PROBE_REGION}")
    
    while True:
        assignments = poll_assignments()
        for assignment in assignments:
            logger.info(f"Executing assignment {assignment['id']} for monitor {assignment['monitor']['name']}")
            
            # Simple HTTP execution for MVP
            if assignment['monitor']['type'] == 'http':
                result = execute_http_check(assignment)
                submit_result(result)
            elif assignment['monitor']['type'] == 'script':
                result = execute_script_check(assignment)
                submit_result(result)
            else:
                logger.warning(f"Unsupported check type: {assignment['monitor']['type']}")
        
        # If no assignments were returned immediately, sleep briefly to prevent tight loops
        if not assignments:
            time.sleep(2)

if __name__ == '__main__':
    main()
