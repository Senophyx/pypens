import os
import hashlib
import logging
import requests
from .auth import AuthHandler
from .ethol import EtholHandler
from .mis import MisHandler
from .exceptions import APIError


_baseLog = logging.getLogger("pypens")
class UserLogAdapter(logging.LoggerAdapter):
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
        self._log = UserLogAdapter(_baseLog, {'username': self._username})

        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Linux; Android 11; SM-A528B Build/RP1A.200720.012; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/87.0.4280.141 Mobile Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive'
        })

    def _request(self, method: str, url: str, **kwargs):
        """Global Session Request with error handling"""
        kwargs.setdefault('timeout', 10)
        try:
            response = self._session.request(method, url, **kwargs)
            return response
        except requests.exceptions.Timeout:
            self._log.error(f'Server Timeout : {url}')
            raise APIError('Server Timeout')
        except requests.exceptions.SSLError:
            self._log.error(f'Max retries exceeded at {url}')
            raise APIError('Max retries exceeded')
        except requests.exceptions.RequestException as req_exc:
            self._log.error(f'Error : {req_exc}')
            raise APIError('Internal Error')