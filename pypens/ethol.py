import json
import base64
from concurrent import futures
from datetime import datetime, timezone
from .exceptions import APIError

class EtholHandler:
    def get_profile(self):
        """Return user profile"""
        if not self.token:
            raise APIError('Invalid session token')
        if not self.tahun or not self.semester or not self.tahun_ajaran:
            self.get_config()
        
        self.log.debug('Fetching profile')
        res_profile = self._request('GET', 'https://ethol.pens.ac.id/api/auth/validasi-token')
        if res_profile.status_code == 200:
            p_data = res_profile.json()
            self.log.debug('Done')
            return {
                "nomor": p_data.get("nomor"),
                "nama": p_data.get("nama"),
                "nrp": p_data.get("nipnrp"),
                "semester": self.semester,
                "tahun_aktif": self.tahun,
                "tahun_ajaran": self.tahun_ajaran
            }
        raise APIError(f'Ethol server Error ({res_profile.status_code})')


    def get_jadwal(self):
        """Return jadwal kuliah"""
        if not self.token:
            raise APIError('Invalid session token')
        if not self.tahun or not self.semester:
            self.get_config()

        self.log.debug('Fetching jadwal')
        res_kuliah = self._request('GET', f'https://ethol.pens.ac.id/api/kuliah?tahun={self.tahun}&semester={self.semester}')
        if res_kuliah.status_code != 200:
            raise APIError(f'Server Error ({res_kuliah.status_code})')

        data_kuliah = res_kuliah.json()
        kuliahs_payload = [{'nomor': mk['nomor'], 'jenisSchema': mk['jenisSchema']} for mk in data_kuliah]
        
        res_waktu = self._request('POST', 
            'https://ethol.pens.ac.id/api/kuliah/hari-kuliah-in', 
            json={'kuliahs': kuliahs_payload, 'tahun': int(self.tahun), 'semester': int(self.semester)}
        )
        if res_waktu.status_code != 200:
            raise APIError(f'Server Error ({res_waktu.status_code})')
        
        data_waktu = res_waktu.json() if res_waktu.status_code == 200 else []
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
                'room': waktu.get('ruang'),
                'dosen': dosen_name,
                'day': waktu.get('hari'),
                'start': waktu.get('jam_awal'),
                'end': waktu.get('jam_akhir')
            })
        self.log.debug(f'{len(jadwal_akhir)} jadwal fetched')
        return jadwal_akhir


    def _fetch_tugas(self, mk):
        matkul_id = mk.get('nomor')
        matkul_name = mk.get('matakuliah', {}).get('nama')

        self.log.debug(f'Fetching tugas for {matkul_name}')
        res_tugas = self._request('GET', f"https://ethol.pens.ac.id/api/tugas?kuliah={matkul_id}&jenisSchema=4")
        if res_tugas.status_code != 200:
            self.log.error(f'Unable to fetch tugas for {matkul_name} ({res_tugas.status_code})')
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
        if not self.token: raise APIError('Invalid session token')
        if not self.tahun or not self.semester:
            self.get_config()

        self.log.debug('Fetching all matkul')
        res_matkul = self._request('GET', f'https://ethol.pens.ac.id/api/kuliah?tahun={self.tahun}&semester={self.semester}')
        if res_matkul.status_code != 200:
            raise APIError(f'Server Error ({res_matkul.status_code})')
        data_matkul = res_matkul.json()
        
        all_tugas = []
        self.log.debug('Fetching all tugas')
        with futures.ThreadPoolExecutor(max_workers=10) as exec:
            tugas_thread = exec.map(self._fetch_tugas, data_matkul)

            for tugas in tugas_thread:
                all_tugas.extend(tugas)
        self.log.debug(f'Successfully fetching {len(all_tugas)} tugas.')
        return all_tugas


    def get_notification(self):
        """Fetch tugas and absen notification"""
        if not self.token: raise APIError('Invalid session token')
        
        self.log.debug('Fetching notifications')
        req_notifs = self._request('GET', 'https://ethol.pens.ac.id/api/notifikasi/mahasiswa?filterNotif=SEMUA')
        if req_notifs.status_code != 200:
            self.log.error(f'Failed to fetch notifications. status {req_notifs.status_code}')
            raise APIError(f'Server Error ({req_notifs.status_code})')
        
        raw_notifs = req_notifs.json()
        all_notifs = []
        
        for notif in raw_notifs:
            kode = notif.get('kodeNotifikasi')
            if kode in ['PRESENSI-KULIAH', 'TUGAS-BARU']:
                notif_type = 'PRESENSI' if kode == 'PRESENSI-KULIAH' else 'TUGAS'
                is_read = True if str(notif.get('status')) == '2' else False

                all_notifs.append({
                    'id': notif.get('idNotifikasi'),
                    'keterangan': notif.get('keterangan'),
                    'is_read': is_read,
                    'notif_type': notif_type,
                    'related_data': notif.get('dataTerkait'),
                    'created_at': notif.get('createdAt'),
                    'time_since': notif.get('waktuNotifikasi'),
                    'created_at_format': notif.get('createdAtIndonesia')
                })
        
        self.log.debug(f'Fetched {len(all_notifs)} notifications')
        return all_notifs


    def absen(self):
        """check open absences and take attendance"""
        if not self.token: raise APIError('Invalid session token')

        try:
            token_b64 = self.token.split('.')[1]
            token_b64 += "=" * ((4 - len(token_b64) % 4) % 4)
            token_json = json.loads(base64.b64decode(token_b64).decode('utf-8'))
            mahasiswa_id = token_json.get('nomor')
        except Exception as e:
            self.log.error(f'Unable to extract mahasiswa_id : {e}')
            raise APIError('Unable to extract mahasiswa_id')
        
        notifs = self.get_notification()
        if not notifs:
            self.log.error('unable to fetch notif')
            return {
                'matkul': None,
                'submitted': False,
                'details': 'no attendance today'
            }

        today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        presensi_notifs = [
            n for n in notifs 
            if n['notif_type'] == 'PRESENSI' and n['created_at'].startswith(today_str)
        ]
        if not presensi_notifs:
            self.log.debug('no attendance today')
            return {
                'matkul': None,
                'submitted': False,
                'details': 'no attendance today'
            }

        for notif in presensi_notifs:
            notif_text = notif.get('keterangan', '')
            matkul_name = notif_text.split('matakuliah ')[-1].strip() if 'matakuliah ' in notif_text else None

            related_data = notif.get('related_data', '')
            if '-' not in related_data:
                continue
            kuliah_id, jenis_schema = related_data.split('-')
            res_kuliah_terakhir = self._request('GET', f'https://ethol.pens.ac.id/api/presensi/terakhir-kuliah?kuliah={kuliah_id}&jenis_schema={jenis_schema}')

            if res_kuliah_terakhir.status_code == 200:
                data_kuliah_terakhir = res_kuliah_terakhir.json()

                if data_kuliah_terakhir.get('ditemukan') and data_kuliah_terakhir.get('open'):
                    absen_key = data_kuliah_terakhir.get('key')
                    payload = {
                        'kuliah': int(kuliah_id), 'mahasiswa': int(mahasiswa_id),
                        'jenis_schema': int(jenis_schema), 'kuliah_asal': int(kuliah_id), 'key': absen_key
                    }
                    res_submit = self._request('POST', 'https://ethol.pens.ac.id/api/presensi/mahasiswa', json=payload)
                    if res_submit.status_code == 200:
                        json_submit = res_submit.json()
                        if json_submit.get('sukses'):
                            self.log.debug(f'Successfully presence for {matkul_name}')
                            return {
                                'matkul': matkul_name,
                                'submitted': True,
                                "details": "successfully attended"
                            }
                        elif json_submit.get('pesan') == "Anda sudah melakukan di sesi kuliah ini":
                            self.log.debug(f'{matkul_name} already attended')
                            continue
                        else:
                            pesan_error = json_submit.get('pesan', 'server error during submission')
                            self.log.error(f'Failed to submit presence for {matkul_name}: {pesan_error}')
                            return {
                                "matkul": matkul_name,
                                "submitted": False,
                                "details": pesan_error
                            }
                    else:
                        self.log.error(f'Failed to submit presence for {matkul_name}')
                        return {
                            "matkul": matkul_name,
                            "submitted": False,
                            "details": "server error during submission"
                        }
                else:
                    self.log.debug(f'Attendance closed for {matkul_name}')
            else:
                raise APIError(f'Server Error ({res_kuliah_terakhir.status_code})')
        
        self.log.debug('All attendance is already attended or closed')
        return {
            'matkul': None,
            'submitted': False,
            "details": "All attendance is already attended or closed"
        }