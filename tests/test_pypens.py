"""Live tests for all pypens public functions against the real ETHOL/MIS API.

Each test prints the actual API output so the response shapes are visible.

Credentials: PYPENS_EMAIL / PYPENS_PASSWORD env vars, or tests/test.env
(EMAIL=... / PASSWORD=...). Session cache lives in tests/users/ (gitignored).

Run: python3 -m unittest discover -s tests -v
"""
import json
import os
import unittest
from pathlib import Path

from pypens import API, APIError

TEST_DIR = Path(__file__).parent

def load_creds():
    email = os.getenv('PYPENS_EMAIL')
    password = os.getenv('PYPENS_PASSWORD')
    env_file = TEST_DIR / 'test.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if '=' not in line:
                continue
            key, value = line.strip().split('=', 1)
            if key == 'EMAIL':
                email = value
            elif key == 'PASSWORD':
                password = value
    if not email or not password:
        raise RuntimeError('Set PYPENS_EMAIL/PYPENS_PASSWORD or create tests/test.env')
    return email, password

def _dump(label, data, max_items=2):
    """Print API output, truncating long lists to max_items entries."""
    print(f'\n  ── {label} ──')
    if isinstance(data, list):
        shown = data[:max_items]
        print('  ' + json.dumps(shown, ensure_ascii=False, indent=2).replace('\n', '\n  '))
        if len(data) > max_items:
            print(f'  ... ({len(data) - max_items} more items, {len(data)} total)')
    elif isinstance(data, dict):
        print('  ' + json.dumps(data, ensure_ascii=False, indent=2).replace('\n', '\n  '))
    else:
        print('  ' + json.dumps(data, ensure_ascii=False))

class TestPypens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.email, cls.password = load_creds()
        cls.api = API(cls.email, cls.password, users_dir=str(TEST_DIR / 'users'), debug=False)
        cls.api.login()

    def test_login(self):
        """login() via CAS flow / session cache"""
        ok = self.api.login()
        _dump('login()', {'ok': ok, 'token_head': (self.api._token or '')[:40] + '...'})
        self.assertTrue(ok)
        self.assertIsNotNone(self.api._token)

    def test_login_cache_reuse(self):
        """second instance reuses cached session without full CAS"""
        api2 = API(self.email, self.password, users_dir=str(TEST_DIR / 'users'), debug=False)
        ok = api2.login()
        _dump('login() (session cache)', {'ok': ok, 'same_token': api2._token == self.api._token})
        self.assertTrue(ok)
        self.assertEqual(api2._token, self.api._token)

    def test_get_config(self):
        tahun = self.api.get_config()
        _dump('get_config()', {
            'tahun': self.api._tahun,
            'semester': self.api._semester,
            'tahun_ajaran': self.api._tahun_ajaran,
            'menit_per_jam': getattr(self.api, '_menit_per_jam', None),
        })
        self.assertTrue(tahun)
        self.assertIsInstance(self.api._tahun, int)
        self.assertIsInstance(self.api._semester, int)
        self.assertTrue(self.api._tahun_ajaran)

    def test_get_profile(self):
        profile = self.api.get_profile()
        _dump('get_profile()', profile)
        for key in ('nomor', 'nama', 'nrp', 'hak_akses', 'semester', 'tahun_aktif', 'tahun_ajaran'):
            self.assertIn(key, profile)
        self.assertIsInstance(profile['hak_akses'], list)

    def test_get_jadwal(self):
        jadwal = self.api.get_jadwal()
        _dump('get_jadwal()', jadwal)
        self.assertIsInstance(jadwal, list)
        self.assertGreater(len(jadwal), 0)
        for item in jadwal:
            for key in ('id', 'matkul', 'kelas', 'pararel', 'room', 'dosen', 'nomor_dosen', 'day', 'start', 'end'):
                self.assertIn(key, item)

    def test_get_tugas(self):
        tugas = self.api.get_tugas()
        _dump('get_tugas()', tugas)
        self.assertIsInstance(tugas, list)

    def test_get_latest_tugas(self):
        tugas = self.api.get_latest_tugas()
        _dump('get_latest_tugas()', tugas)
        self.assertIsInstance(tugas, list)

    def test_get_notification(self):
        notifs = self.api.get_notification()
        _dump('get_notification()', notifs)
        self.assertIsInstance(notifs, list)
        for notif in notifs:
            self.assertIn('notif_type', notif)
            self.assertIn('url_web', notif)

    def test_get_unread_notification_count(self):
        jumlah = self.api.get_unread_notification_count()
        _dump('get_unread_notification_count()', jumlah)
        self.assertIsInstance(jumlah, int)
        self.assertGreaterEqual(jumlah, 0)

    def test_baca_notifikasi_error_path(self):
        """fake id must be rejected; real ids untouched to keep account state"""
        with self.assertRaises(APIError) as ctx:
            self.api.baca_notifikasi('fake-id-for-test')
        _dump('baca_notifikasi(fake-id)', {'raised': type(ctx.exception).__name__, 'message': str(ctx.exception)})

    def test_absen(self):
        hasil = self.api.absen()
        _dump('absen()', hasil)
        self.assertIsInstance(hasil, dict)
        self.assertIn('absen', hasil)
        self.assertIn('details', hasil)
        self.assertIsInstance(hasil['absen'], list)

    def test_get_presensi(self):
        presensi = self.api.get_presensi()
        _dump('get_presensi()', presensi)
        self.assertIn('presensi', presensi)
        self.assertGreater(len(presensi['presensi']), 0)
        for item in presensi['presensi']:
            self.assertIn('matkul', item)
            self.assertIn('week', item)
            self.assertEqual(len(item['week']), 16)

class TestPypensErrors(unittest.TestCase):
    def test_wrong_password(self):
        email, _ = load_creds()
        bad = API(email, 'wrong-password-test', users_dir=str(TEST_DIR / 'users'), debug=False)
        with self.assertRaises(APIError) as ctx:
            bad.login()
        _dump('login() (wrong password)', {'raised': type(ctx.exception).__name__, 'message': str(ctx.exception)})

    def test_session_required(self):
        email, password = load_creds()
        fresh = API(email, password, users_dir=str(TEST_DIR / 'users'), debug=False)
        with self.assertRaises(APIError) as ctx:
            fresh.get_profile()
        _dump('get_profile() (no session)', {'raised': type(ctx.exception).__name__, 'message': str(ctx.exception)})

class TestAPIError(unittest.TestCase):
    def test_api_error_is_exception(self):
        err = APIError('test message')
        _dump('APIError', {'is_exception': issubclass(APIError, Exception), 'str': str(err)})
        self.assertTrue(issubclass(APIError, Exception))
        self.assertEqual(str(err), 'test message')

if __name__ == '__main__':
    unittest.main(verbosity=2)
