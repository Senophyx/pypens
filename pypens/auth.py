import os
import re
import json
from datetime import datetime
from urllib.parse import urljoin
from .exceptions import APIError

class AuthHandler:
    def _load_session(self):
        """Load session from users file, validate it, and refresh if needed"""
        if not os.path.exists(self._session_file): return False

        try:
            with open(self._session_file, 'r') as s_file:
                s_data = json.load(s_file)
            
            if s_data.get('hash') != self._user_hash:
                self._log.warning('Hash mismatch')
                return False
            
            self._token = s_data.get('token')
            cookies = s_data.get('cookies', {})
            refresh_token = s_data.get('refresh_token') or cookies.get('refresh_token')
            if self._token:
                self._session.cookies.set('token', self._token, domain='ethol.pens.ac.id', path='/')
            if refresh_token:
                self._session.cookies.set('refresh_token', refresh_token, domain='ethol.pens.ac.id', path='/api/auth')
            self._session.headers.update({
                'Accept': 'application/json, text/plain, */*'
            })

            self._log.debug('Validating session')
            s_res = self._request('GET', 'https://ethol.pens.ac.id/api/auth/validasi-token')

            if s_res.status_code == 200:
                self._log.debug('Session valid')
                return True

            self._log.warning('Session expired, trying refresh')
            if self._refresh():
                self._log.debug('Session refreshed')
                return True

            self._log.warning('Refresh failed, re-login needed')
            return False

        except Exception as e:
            self._log.error(f'Unable to load session : {e}')
            return False

    def _refresh(self):
        """Renew access token using the refresh_token cookie"""
        self._log.debug('Refreshing token')
        try:
            res_refresh = self._request('POST', 'https://ethol.pens.ac.id/api/auth/refresh')
            if res_refresh.status_code == 200:
                self._token = self._session.cookies.get('token')
                self._save_session()
                return True
            self._log.warning(f'Refresh failed ({res_refresh.status_code})')
        except Exception as e:
            self._log.error(f'Unable to refresh session : {e}')
        return False

    def _save_session(self):
        """Save session to user data"""
        try:
            s_data = {
                'hash': self._user_hash,
                'token': self._token,
                'refresh_token': self._session.cookies.get('refresh_token', domain='ethol.pens.ac.id', path='/api/auth'),
                'cookies': self._session.cookies.get_dict(),
                'last_login': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(self._session_file, 'w') as s_file: json.dump(s_data, s_file, indent=4)
            self._log.debug(f'Session saved to {self._session_file}')

        except Exception as e: 
            self._log.error(f'Unable to save session : {e}')

    def login(self):
        """Login to ETHOL via CAS SSO with cache system"""
        if self._load_session():
            if not self._tahun or not self._semester:
                self.get_config()
            self._save_session()
            return True

        self._log.debug('Getting CAS redirect url')
        res_redirect = self._request('GET', 'https://ethol.pens.ac.id/api/auth/cas-redirect', allow_redirects=False)
        cas_url = res_redirect.headers.get('Location')
        if not cas_url:
            self._log.error('Unable to find CAS url')
            raise APIError('Unable to find CAS url')

        self._log.debug('Getting CAS login form')
        res_login_page = self._request('GET', cas_url)
        lt_match = re.search(r'name="lt"\s+value="([^"]+)"', res_login_page.text)
        event_match = re.search(r'name="_eventId"\s+value="([^"]+)"', res_login_page.text)
        action_match = re.search(r'<form[^>]+action="([^"]+)"', res_login_page.text)

        if not lt_match or not event_match:
            self._log.error('Unable to find CAS form')
            raise APIError('Unable to find CAS url')

        post_url = urljoin(cas_url, action_match.group(1)) if action_match else cas_url

        payload = {
            'username': self._email,
            'password': self._password,
            'lt': lt_match.group(1),
            '_eventId': event_match.group(1),
            'submit': 'LOGIN'
        }

        self._log.debug('Sending creds to CAS')
        res_post_login = self._request('POST', post_url, data=payload, allow_redirects=False,
                                       headers={'Origin': 'https://login.pens.ac.id', 'Referer': cas_url})

        ticket_url = res_post_login.headers.get('Location')
        if res_post_login.status_code != 302 or not ticket_url:
            self._log.error('Invalid email or password')
            raise APIError('Invalid email or password')

        if ticket_url.startswith('http://'):
            ticket_url = ticket_url.replace('http://', 'https://', 1)

        self._log.debug('Validating ticket')
        self._request('GET', ticket_url, allow_redirects=False)

        self._token = self._session.cookies.get('token')
        if not self._token:
            self._log.error('Unable to obtain token')
            raise APIError('Unable to obtain token')

        self._log.debug('Loading app shell')
        self._request('GET', 'https://ethol.pens.ac.id/auth/cas')

        self._log.debug('Validating token')
        res_validate = self._request('GET', 'https://ethol.pens.ac.id/api/auth/validasi-token')
        if res_validate.status_code != 200:
            self._log.error('Unable to obtain token')
            raise APIError('Unable to obtain token')

        self._log.debug('Successfully login')
        self._save_session()

        if not self._tahun or not self._semester: self.get_config()
        return True

    def get_config(self):
        """Get current user tahun and semester"""
        if not self._token:
            raise APIError('Invalid session token')

        self._log.debug('Getting config')
        res_config = self._request('GET', 'https://ethol.pens.ac.id/api/auth/config')
        
        if res_config.status_code == 200:
            data = res_config.json()
            self._tahun = data.get('tahun_aktif')
            self._semester = data.get('semester_aktif')
            self._tahun_ajaran = data.get('tahun_ajaran_aktif')
            self._menit_per_jam = data.get('menit_per_jam')
            self._log.debug('Config obtained')
            return True
        
        self._log.error('Unable to load config')
        raise APIError('Unable to load config')