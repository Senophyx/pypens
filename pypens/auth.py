import os
import re
import json
from datetime import datetime
from .exceptions import APIError

class AuthHandler:
    def _load_session(self):
        """Load session from users file and check if still valid"""
        if not os.path.exists(self.session_file): return False

        try:
            with open(self.session_file, 'r') as s_file:
                s_data = json.load(s_file)
            
            if s_data.get('hash') != self.user_hash:
                self.log.warning('Hash mismatch')
                return False
            
            self.token = s_data.get('token')
            self.session.cookies.update(s_data.get('cookies', {}))
            self.session.headers.update({
                'Token': self.token,
                'Accept': 'application/json, text/plain, */*'
            })

            self.log.debug('Validating session')
            s_res = self._request('GET', 'https://ethol.pens.ac.id/api/auth/validasi-token')

            if s_res.status_code == 200:
                self.log.debug('Session valid')
                return True
            else:
                self.log.warning('Session expired, trying to re-login now')
                return False

        except Exception as e:
            self.log.error(f'Unable to load session : {e}')


    def _save_session(self):
        """Save session to user data"""
        try:
            s_data = {
                'hash': self.user_hash,
                'token': self.token,
                'cookies': self.session.cookies.get_dict(),
                'last_login': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(self.session_file, 'w') as s_file: json.dump(s_data, s_file, indent=4)
            self.log.debug(f'Session saved to {self.session_file}')

        except Exception as e: 
            self.log.error(f'Unable to save session : {e}')

    
    def login(self):
        """Login to CAS with Cache System"""
        if self._load_session():
            if not self.tahun or not self.semester:
                self.get_config()
            self._save_session()
            return True
        
        self.log.debug('Getting CAS url')
        res_login_page = self._request('GET', 'https://ethol.pens.ac.id/cas/', allow_redirects=True)

        self.log.debug('Getting form ticket/lt')
        lt_match = re.search(r'name="lt"\s+value="([^"]+)"', res_login_page.text)
        event_match = re.search(r'name="_eventId"\s+value="([^"]+)"', res_login_page.text)

        if not lt_match or not event_match:
            self.log.error('Unable to find CAS url')
            raise APIError('Unable to find CAS url')
        
        payload = {
            'username': self.email,
            'password': self.password,
            'lt': lt_match.group(1),
            '_eventId': event_match.group(1),
            'submit': 'LOGIN'
        }

        self.log.debug('Sending creds to CAS')
        res_post_login = self._request('POST', res_login_page.url, data=payload, allow_redirects=False)

        if res_post_login.status_code != 302:
            self.log.error('Invalid email or password')
            raise APIError('Invalid email or password')
        
        self.log.debug('Validating ticket')
        ticket_url = res_post_login.headers.get('Location')
        if ticket_url and ticket_url.startswith('http://'):
            ticket_url = ticket_url.replace('http://', 'https://', 1)

        self.log.debug('Getting JWT token')
        res_jwt = self._request('GET', ticket_url, allow_redirects=True)
        token_match = re.search(r"localStorage\.setItem\('token',\s*'([^']+)'\)", res_jwt.text)

        if token_match:
            self.token = token_match.group(1)
            self.session.headers.update({
                'Token': self.token,
                'Accept': 'application/json, text/plain, */*'
            })
            self.log.debug("Successfully login")
            self._save_session()

            if not self.tahun or not self.semester: self.get_config()
            return True
        
        else:
            self.log.error('Unable to obtain token')
            raise APIError('Unable to obtain token')


    def get_config(self):
        """Get current user tahun and semester"""
        if not self.token:
            raise APIError('Invalid session token')

        self.log.debug('Getting config')
        res_config = self._request('GET', 'https://ethol.pens.ac.id/api/auth/config')
        
        if res_config.status_code == 200:
            data = res_config.json()
            self.tahun = data.get('tahun_aktif')
            self.semester = data.get('semester_aktif')
            self.tahun_ajaran = data.get('tahun_ajaran_aktif')
            self.log.debug('Config obtained')
            return True
        
        self.log.error('Unable to load config')
        raise APIError('Unable to load config')