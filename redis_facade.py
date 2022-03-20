import os
import redis
import simplejson as json
from datetime import timedelta
from urllib.parse import urlparse

SESSION_DURATION = timedelta(minutes=30)


class RedisFacade:
    def __init__(self, host: str='localhost', port: int=6379):
        redis_url = os.environ.get("REDIS_TLS_URL")
        if redis_url is None:
            self.r = redis.Redis(db=0, decode_responses=True)
        else:
            url = urlparse(redis_url)
            self.r = redis.Redis(db=0, host=url.hostname, port=url.port, username=url.username, password=url.password, ssl=True, ssl_cert_reqs=None, decode_responses=True)


    def save_nav_stack(self, user_id: int, nav_stack: list[str]) -> None:
        self.r.setex(user_id, SESSION_DURATION, json.dumps(nav_stack))


    def load_nav_stack(self, user_id: int) -> list[str]:
        session_json = self.r.get(user_id)
        return None if session_json is None else json.loads(session_json)
