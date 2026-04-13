import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from .exceptions import APIError

class MisHandler:
    def get_presensi(self):
        """Return presensi for all matkul"""
        if not self.tahun or not self.semester:
            self.get_config()

        self.log.debug('Authenticating to OnlineMIS PENS')
        mis_session = requests.Session()
        mis_session.headers.update({
            'User-Agent': self.session.headers.get('User-Agent'),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })

        try:
            mis_session.get('https://online.mis.pens.ac.id/', timeout=10)
            url_service = 'https://online.mis.pens.ac.id/index.php?Login=1&halAwal=1'
            res_cas = mis_session.get(url_service, allow_redirects=True, timeout=10)

            soup_cas = BeautifulSoup(res_cas.text, 'html.parser')
            form = soup_cas.find('form', id='fm1')
            
            if form:
                action_url = form.get('action')
                post_url = urljoin(res_cas.url, action_url)
                lt_input = form.find('input', {'name': 'lt'})
                event_input = form.find('input', {'name': '_eventId'})

                if lt_input and event_input:
                    payload = {
                        'username': self.email,
                        'password': self.password,
                        'lt': lt_input.get('value'),
                        '_eventId': event_input.get('value'),
                        'submit': 'LOGIN'
                    }

                    headers_login = {
                        'Origin': 'https://login.pens.ac.id',
                        'Referer': res_cas.url,
                        'Content-Type': 'application/x-www-form-urlencoded'
                    }

                    self.log.debug('Sending creds to OnlineMIS CAS')
                    res_post = mis_session.post(post_url, data=payload, headers=headers_login, allow_redirects=True, timeout=15)
                    
                    if "Selamat Datang di Online.MIS PENS" not in res_post.text:
                        self.log.error("Unable login to OnlineMIS.")
                        return {"presensi": []}
                else:
                    self.log.error('Invalid CAS form')
                    return {"presensi": []}
            else:
                self.log.debug('Login Form not found.')

            self.log.debug('Initializing MIS absen module')
            res_mabsen = mis_session.get('https://online.mis.pens.ac.id/mAbsen.php', timeout=10)
            
            if "showData" not in res_mabsen.text:
                self.log.error('Unable to initiate MIS session')
                return {'presensi': []}
            
            self.log.debug('Fetching presensi')
            random_sid = random.random()
            url_absen = f"https://online.mis.pens.ac.id/absen.php?valTahun={self.tahun}&valSemester={self.semester}&sid={random_sid}"

            headers_mabsen = {'Referer': 'https://online.mis.pens.ac.id/mAbsen.php'}
            res_absen = mis_session.get(url_absen, headers=headers_mabsen, timeout=10)

            self.log.debug('Parsing HTML Presensi')
            soup = BeautifulSoup(res_absen.text, 'html.parser')
            table = soup.find('table', class_='presensi-table')
            if not table:
                self.log.error('Presensi table not found')
                return {'presensi': []}
                
            presensi_data = []
            for row in table.find_all('tr'):
                if row.find('th'):
                    continue

                cols = row.find_all('td')
                if len(cols) >= 18:
                    matkul_name = cols[1].get_text(strip=True)
                    week_data = []

                    for i in range(2, 18):
                        status_text = cols[i].get_text(strip=True).upper()
                    
                        if status_text in ['H', 'HH']: status = True
                        elif status_text == '-': status = None
                        else: status = False

                        week_data.append(status)

                    presensi_data.append({
                        "matkul": matkul_name,
                        "week": week_data
                    })

            self.log.debug(f'Done fetching presensi for {len(presensi_data)} matkul')
            return {'presensi': presensi_data}
        
        except requests.exceptions.RequestException as e:
            self.log.error(f"Error fetching OnlineMIS: {e}")
            raise APIError("Error fetching OnlineMIS")