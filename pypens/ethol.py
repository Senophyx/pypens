import json
import base64
from concurrent import futures
from .exceptions import APIError

class EtholHandler:
    def get_profile(self):
        """Return user profile"""
        if not self._token:
            raise APIError('Invalid session token')
        if not self._tahun or not self._semester or not self._tahun_ajaran:
            self.get_config()
        
        self._log.debug('Fetching profile')
        res_profile = self._request('GET', 'https://ethol.pens.ac.id/api/auth/validasi-token')
        if res_profile.status_code == 200:
            p_data = res_profile.json()
            self._log.debug('Done')
            return {
                "nomor": p_data.get("nomor"),
                "nama": p_data.get("nama"),
                "nrp": p_data.get("nipnrp"),
                "hak_akses": p_data.get("hakAkses"),
                "semester": self._semester,
                "tahun_aktif": self._tahun,
                "tahun_ajaran": self._tahun_ajaran
            }
        raise APIError(f'Ethol server Error ({res_profile.status_code})')

    def get_jadwal(self):
        """Return jadwal kuliah"""
        if not self._token:
            raise APIError('Invalid session token')
        if not self._tahun or not self._semester:
            self.get_config()

        self._log.debug('Fetching jadwal')
        res_kuliah = self._request('GET', f'https://ethol.pens.ac.id/api/kuliah?tahun={self._tahun}&semester={self._semester}')
        if res_kuliah.status_code != 200:
            raise APIError(f'Server Error ({res_kuliah.status_code})')

        data_kuliah = res_kuliah.json()
        kuliahs_payload = [{'nomor': mk['nomor'], 'jenisSchema': mk['jenisSchema']} for mk in data_kuliah]
        
        res_waktu = self._request('POST', 
            'https://ethol.pens.ac.id/api/kuliah/hari-kuliah-in', 
            json={'kuliahs': kuliahs_payload, 'tahun': int(self._tahun), 'semester': int(self._semester)}
        )
        if res_waktu.status_code != 200:
            raise APIError(f'Server Error ({res_waktu.status_code})')
        
        data_waktu = res_waktu.json()
        waktu_dict = { item['kuliah']: item for item in data_waktu }
        jadwal_akhir = []

        for mk in data_kuliah:
            waktu = waktu_dict.get(mk.get('nomor'), {})
            dosen_name = mk.get('dosen')
            if mk.get("gelar_dpn"): dosen_name = f"{mk['gelar_dpn']} {dosen_name}"
            if mk.get("gelar_blk"): dosen_name = f"{dosen_name}, {mk['gelar_blk']}"
            
            jadwal_akhir.append({
                'id': mk.get('nomor'),
                'matkul': mk.get("matakuliah", {}).get("nama"),
                'kelas': mk.get('kode_kelas'),
                'pararel': mk.get('pararel'),
                'room': waktu.get('ruang'),
                'dosen': dosen_name,
                'nomor_dosen': mk.get('nomor_dosen'),
                'day': waktu.get('hari'),
                'start': waktu.get('jam_awal'),
                'end': waktu.get('jam_akhir')
            })
        self._log.debug(f'{len(jadwal_akhir)} jadwal fetched')
        return jadwal_akhir

    def _fetch_tugas(self, mk):
        matkul_id = mk.get('nomor')
        matkul_name = mk.get('matakuliah', {}).get('nama')
        jenis_schema = mk.get('jenisSchema')

        self._log.debug(f'Fetching tugas for {matkul_name}')
        res_tugas = self._thread_request('GET', f"https://ethol.pens.ac.id/api/tugas?kuliah={matkul_id}&jenisSchema={jenis_schema}",
                                         self._clone_session())
        if res_tugas is None or res_tugas.status_code != 200:
            self._log.error(f'Unable to fetch tugas for {matkul_name}' +
                            (f" ({res_tugas.status_code})" if res_tugas is not None else ''))
            return []
        
        data_tugas = res_tugas.json()
        hasil = []
        for tugas in data_tugas:
            submit_time = tugas.get('submission_time')
            hasil.append({
                'id': matkul_id,
                'matkul': matkul_name,
                'title': tugas.get('title'),
                'description': tugas.get('description'),
                'deadline': tugas.get('deadline_indonesia') or tugas.get('deadline'),
                "submited": True if submit_time is not None else False
            })
        
        return hasil

    def get_tugas(self):
        """Return all tugas"""
        if not self._token: raise APIError('Invalid session token')
        if not self._tahun or not self._semester:
            self.get_config()

        self._log.debug('Fetching all matkul')
        res_matkul = self._request('GET', f'https://ethol.pens.ac.id/api/kuliah?tahun={self._tahun}&semester={self._semester}')
        if res_matkul.status_code != 200:
            raise APIError(f'Server Error ({res_matkul.status_code})')
        data_matkul = res_matkul.json()
        
        all_tugas = []
        self._log.debug('Fetching all tugas')
        with futures.ThreadPoolExecutor(max_workers=10) as exec:
            tugas_thread = exec.map(self._fetch_tugas, data_matkul)

            for tugas in tugas_thread:
                all_tugas.extend(tugas)
        self._log.debug(f'Successfully fetching {len(all_tugas)} tugas.')
        return all_tugas

    def get_latest_tugas(self):
        """Return the latest tugas per matkul via a single batch call"""
        if not self._token: raise APIError('Invalid session token')
        if not self._tahun or not self._semester:
            self.get_config()

        self._log.debug('Fetching all matkul')
        res_matkul = self._request('GET', f'https://ethol.pens.ac.id/api/kuliah?tahun={self._tahun}&semester={self._semester}')
        if res_matkul.status_code != 200:
            raise APIError(f'Server Error ({res_matkul.status_code})')
        data_matkul = res_matkul.json()

        self._log.debug('Fetching tugas terakhir')
        payload = {'kuliahs': [{'nomor': mk['nomor']} for mk in data_matkul]}
        res_tugas = self._request('POST', 'https://ethol.pens.ac.id/api/tugas/tugas-terakhir-mahasiswa', json=payload)
        if res_tugas.status_code != 200:
            raise APIError(f'Server Error ({res_tugas.status_code})')

        hasil = [tugas for tugas in res_tugas.json() if tugas is not None]
        self._log.debug(f'Successfully fetching {len(hasil)} tugas terakhir.')
        return hasil

    def get_notification(self):
        """Fetch all notifications"""
        if not self._token: raise APIError('Invalid session token')
        
        self._log.debug('Fetching notifications')
        req_notifs = self._request('GET', 'https://ethol.pens.ac.id/api/notifikasi/mahasiswa?filterNotif=SEMUA')
        if req_notifs.status_code != 200:
            self._log.error(f'Failed to fetch notifications. status {req_notifs.status_code}')
            raise APIError(f'Server Error ({req_notifs.status_code})')
        
        raw_notifs = req_notifs.json()
        all_notifs = []
        
        for notif in raw_notifs:
            kode = notif.get('kodeNotifikasi') or ''
            all_notifs.append({
                'id': notif.get('idNotifikasi'),
                'keterangan': notif.get('keterangan'),
                'is_read': True if str(notif.get('status')) == '2' else False,
                'notif_type': kode.split('-')[0] if '-' in kode else kode,
                'related_data': notif.get('dataTerkait'),
                'url_web': notif.get('urlWeb'),
                'created_at': notif.get('createdAt'),
                'time_since': notif.get('waktuNotifikasi'),
                'created_at_format': notif.get('createdAtIndonesia')
            })
        
        self._log.debug(f'Fetched {len(all_notifs)} notifications')
        return all_notifs

    def get_unread_notification_count(self):
        """Return the number of unread notifications"""
        if not self._token: raise APIError('Invalid session token')

        self._log.debug('Fetching unread notification count')
        res_notifs = self._request('GET', 'https://ethol.pens.ac.id/api/notifikasi/mahasiswa-belum-baca')
        if res_notifs.status_code != 200:
            raise APIError(f'Server Error ({res_notifs.status_code})')

        jumlah = res_notifs.json().get('jumlah', 0)
        self._log.debug(f'{jumlah} notifications unread')
        return jumlah

    def baca_notifikasi(self, id_notifikasi: str):
        """Mark a notification as read"""
        if not self._token: raise APIError('Invalid session token')

        self._log.debug(f'Marking notification {id_notifikasi} as read')
        res_baca = self._request('PUT', 'https://ethol.pens.ac.id/api/notifikasi/mahasiswa-baca-notif',
                                 json={'idNotifikasi': id_notifikasi})
        if res_baca.status_code != 200:
            raise APIError(f'Server Error ({res_baca.status_code})')
        return True

    def absen(self):
        """Check open attendance sessions and take attendance"""
        if not self._token: raise APIError('Invalid session token')
        if not self._tahun or not self._semester:
            self.get_config()

        try:
            token_b64 = self._token.split('.')[1]
            token_b64 += "=" * ((4 - len(token_b64) % 4) % 4)
            token_json = json.loads(base64.b64decode(token_b64).decode('utf-8'))
            mahasiswa_id = token_json.get('nomor')
        except Exception as e:
            self._log.error(f'Unable to extract mahasiswa_id : {e}')
            raise APIError('Unable to extract mahasiswa_id')

        self._log.debug('Fetching all matkul')
        res_matkul = self._request('GET', f'https://ethol.pens.ac.id/api/kuliah?tahun={self._tahun}&semester={self._semester}')
        if res_matkul.status_code != 200:
            raise APIError(f'Server Error ({res_matkul.status_code})')
        data_matkul = res_matkul.json()

        def _cek_absen(mk):
            """Return [(mk, sesi)] for open sessions on this matkul"""
            buka = []
            res_aktif = self._thread_request('GET', 'https://ethol.pens.ac.id/api/presensi/aktif-kuliah',
                                             self._clone_session(),
                                             params={'kuliah': mk['nomor'], 'jenis_schema': mk['jenisSchema']})
            if res_aktif is not None and res_aktif.status_code == 200:
                for sesi in res_aktif.json() or []:
                    if sesi.get('open') in (1, '1', True):
                        buka.append((mk, sesi))
            return buka

        open_list = []
        self._log.debug('Checking open attendance sessions')
        with futures.ThreadPoolExecutor(max_workers=10) as exec:
            for buka in exec.map(_cek_absen, data_matkul):
                open_list.extend(buka)

        if not open_list:
            self._log.debug('No open attendance')
            return {'absen': [], 'details': 'no open attendance'}

        hasil = []
        for mk, sesi in open_list:
            matkul_name = mk.get('matakuliah', {}).get('nama')
            sesi_key = sesi.get('key')

            res_riwayat = self._request('GET', 'https://ethol.pens.ac.id/api/presensi/riwayat',
                                        params={'kuliah': mk['nomor'], 'jenis_schema': mk['jenisSchema'], 'nomor': mahasiswa_id})
            riwayat = res_riwayat.json() if res_riwayat.status_code == 200 else []
            if any(r.get('key') == sesi_key for r in riwayat):
                self._log.debug(f'{matkul_name} already attended')
                hasil.append({'matkul': matkul_name, 'submitted': False, 'details': 'already attended'})
                continue

            payload = {
                'kuliah': int(mk['nomor']),
                'jenis_schema': int(mk['jenisSchema']),
                'mahasiswa': int(mahasiswa_id),
                'key': sesi_key,
                'kuliah_asal': mk.get('kuliah_asal')
            }
            res_submit = self._request('POST', 'https://ethol.pens.ac.id/api/presensi/mahasiswa', json=payload)
            if res_submit.status_code == 200:
                json_submit = res_submit.json()
                if json_submit.get('sukses'):
                    self._log.debug(f'Successfully presence for {matkul_name}')
                    verifikasi = {}
                    res_riwayat2 = self._request('GET', 'https://ethol.pens.ac.id/api/presensi/riwayat',
                                                 params={'kuliah': mk['nomor'], 'jenis_schema': mk['jenisSchema'], 'nomor': mahasiswa_id})
                    if res_riwayat2.status_code == 200:
                        for r in res_riwayat2.json() or []:
                            if r.get('key') == sesi_key:
                                verifikasi = {'nomor': r.get('nomor'), 'tanggal': r.get('tanggal'),
                                              'waktu_indonesia': r.get('waktu_indonesia')}
                                break
                    hasil.append({'matkul': matkul_name, 'submitted': True,
                                  'details': json_submit.get('pesan', 'successfully attended'),
                                  'verifikasi': verifikasi})
                else:
                    pesan_error = json_submit.get('pesan', 'server error during submission')
                    self._log.error(f'Failed to submit presence for {matkul_name}: {pesan_error}')
                    hasil.append({'matkul': matkul_name, 'submitted': False, 'details': pesan_error})
            else:
                self._log.error(f'Failed to submit presence for {matkul_name} ({res_submit.status_code})')
                hasil.append({'matkul': matkul_name, 'submitted': False,
                              'details': f'server error during submission ({res_submit.status_code})'})

        self._log.debug(f'Attendance processed for {len(hasil)} matkul')
        return {'absen': hasil, 'details': f'{len(hasil)} matkul diproses'}
