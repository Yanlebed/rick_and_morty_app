import time


class SimpleRateLimiter:
    def __init__(self, requests_per_minute=30):
        self.requests_per_minute = requests_per_minute
        self.requests = {}  # IP -> list of request timestamps

    def is_rate_limited(self, ip: str) -> bool:
        current_time = time.time()

        # Initialize if this is the first request from this IP
        if ip not in self.requests:
            self.requests[ip] = []

        # Remove timestamps older than 1 minute
        self.requests[ip] = [ts for ts in self.requests[ip] if current_time - ts < 60]

        # Check if rate limited
        if len(self.requests[ip]) >= self.requests_per_minute:
            return True

        # Add current timestamp
        self.requests[ip].append(current_time)

        # Clean up old IPs to prevent memory leaks
        if current_time % 300 < 1:  # Approximately every 5 minutes
            self._cleanup()

        return False

    def _cleanup(self):
        """Remove IPs with no recent requests to prevent memory leaks"""
        current_time = time.time()
        ips_to_remove = []

        for ip, timestamps in self.requests.items():
            if not timestamps or current_time - max(timestamps) > 300:  # No activity for 5 minutes
                ips_to_remove.append(ip)

        for ip in ips_to_remove:
            del self.requests[ip]
