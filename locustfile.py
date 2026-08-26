from locust import HttpUser, task, between

class VectoTraceLoadTest(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        # We assume an access token is injected via environment or generated for the test
        self.client.headers.update({"Authorization": "Bearer TEST_TOKEN"})

    @task(3)
    def view_dashboard(self):
        # Simulates a user polling their monitors
        self.client.get("/api/v1/orgs/1/monitors/")
        
    @task(1)
    def check_incidents(self):
        self.client.get("/api/v1/orgs/1/incidents/")
        
    @task(5)
    def public_status_page(self):
        # Simulates high traffic on public status pages during an incident
        self.client.get("/api/v1/status-pages/public-example/")
