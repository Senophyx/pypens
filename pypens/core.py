import os
import hashlib
import logging
import threading
import time
import requests
from .auth import AuthHandler
from .ethol import EtholHandler
from .mis import MisHandler
from .exceptions import APIError


_baseLog = logging.getLogger("pypens")
class _UserLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"{self.extra['username']} :: {msg}", kwargs
    

class API(AuthHandler, EtholHandler, MisHandler):
    def __init__(self, email: str, password: str, users_dir: str = 'users', debug: bool = False):
        self._email = email
        self._password = password
        self._token = None
        self._tahun = None
        self._semester = None
        self._tahun_ajaran = None
        self._menit_per_jam = None
        self._users_dir = users_dir
        os.makedirs(self._users_dir, exist_ok=True)
        self._username = self._email.split('@')[0]
        self._session_file = os.path.join(self._users_dir, f"{self._username}.json")
        self._user_hash = hashlib.sha256(f'{self._email}:{self._password}'.encode()).hexdigest()

        log_level = logging.DEBUG if debug else logging.INFO
        logging.basicConfig(
            format="%(asctime)s :: %(levelname)s :: %(message)s", 
            datefmt="%Y-%m-%d %H:%M:%S",
            level=log_level
        )
        _baseLog.setLevel(log_level)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        self._log = _UserLogAdapter(_baseLog, {'username': self._username})

        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Linux; Android 11; SM-A528B Build/RP1A.200720.012; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/87.0.4280.141 Mobile Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive'
        })
        self._refresh_lock = threading.Lock()

    def _clone_session(self):
        """Create an independent session with copied headers and cookies (thread-safe)"""
        session = requests.Session()
        session.headers.update(self._session.headers)
        session.cookies.update(self._session.cookies)
        return session

    def _thread_request(self, method: str, url: str, session, **kwargs):
        """Request via a dedicated session inside a worker thread; retries on network failure,
        returns None if all attempts fail"""
        kwargs.setdefault('timeout', 10)
        attempt = 1
        while True:
            try:
                response = session.request(method, url, **kwargs)
                if response.status_code == 401 and '/api/auth/' not in url:
                    with self._refresh_lock:
                        if self._refresh():
                            session.cookies.set('token', self._token, domain='ethol.pens.ac.id', path='/')
                            response = session.request(method, url, **kwargs)
                return response
            except requests.exceptions.RequestException as req_exc:
                if attempt >= 5:
                    self._log.error(f'Error : {req_exc}')
                    return None
                self._log.debug(f'Error (attempt {attempt}): {req_exc}')
                time.sleep(0.5 * attempt)
                attempt += 1

    def _request(self, method: str, url: str, **kwargs):
        """Global Session Request with error handling and one-shot refresh on 401"""
        kwargs.setdefault('timeout', 10)
        try:
            response = self._session.request(method, url, **kwargs)
            if response.status_code == 401 and '/api/auth/' not in url:
                self._log.debug('Token expired, refreshing session')
                if self._refresh():
                    response = self._session.request(method, url, **kwargs)
            return response
        except requests.exceptions.Timeout:
            self._log.error(f'Server Timeout : {url}')
            raise APIError('Server Timeout')
        except requests.exceptions.SSLError:
            self._log.error(f'SSL Error at {url}')
            raise APIError('SSL Error')
        except requests.exceptions.RequestException as req_exc:
            self._log.error(f'Error : {req_exc}')
            raise APIError('Internal Error')