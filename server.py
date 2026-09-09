import hashlib
import threading
from collections import defaultdict, deque
from datetime import datetime
from time import time
from zoneinfo import ZoneInfo

from pypens import API, APIError
import uvicorn
import logging
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

app = FastAPI(
    title='PENS API Wrapper',
    description=(
        'Unofficial REST API wrapper for Politeknik Elektronika Negeri Surabaya (PENS).\n\n'
        'It exposes the [PyPENS](https://github.com/Senophyx/pypens) SDK over HTTP, covering '
        'the ETHOL e-learning system (schedule, tasks, notifications, attendance) and the '
        'Online-MIS attendance recap. All endpoints require a PENS NetID and password.\n\n'
        '**Auth note:** credentials are sent in the JSON body of every request and are never '
        'stored. Sessions are cached in memory per user.'
    ),
    version='1.0',
)
logging.basicConfig(
    format="%(asctime)s :: %(levelname)s :: %(message)s", 
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO)
log = logging.getLogger("Router")

@app.middleware("http")
async def custom_logging(request: Request, call_next):
    response = await call_next(request)
    user = getattr(request.state, "user", "guest")
    log.info(f"[{user}] {request.method} {request.url.path} - {response.status_code}")
    return response

# ==== EXCEPTION HANDLING ====
@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    log.error(exc)
    return JSONResponse(
        status_code=401,
        content={'error': True, 'msg': str(exc), 'data': None}
    )

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 405:
        msg = "Method not allowed"
    elif exc.status_code == 404:
        msg = "Endpoint not found"
    else:
        msg = str(exc.detail)

    log.warning(f"HTTP {exc.status_code} on {request.method} {request.url.path}")

    return JSONResponse(
        status_code=exc.status_code,
        content={'error': True, 'msg': msg, 'data': None}
    )

@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception):
    log.exception(f'Unhandled error on {request.method} {request.url.path}')
    return JSONResponse(
        status_code=500,
        content={'error': True, 'msg': 'internal error', 'data': None}
    )

# =============================

class UserCreds(BaseModel):
    email: str = Field(..., description='PENS NetID email, e.g. `test@it.student.pens.ac.id`',
                       examples=['test@it.student.pens.ac.id'])
    password: str = Field(..., description='PENS NetID password', examples=['your-password'])

_RATE_LIMIT = 20
_RATE_WINDOW = 60.0
_hits = defaultdict(deque)

_COURSE_START = 6
_COURSE_END = 18

def _is_course_hours() -> bool:
    """True if now is Mon-Fri between 06:00 and 18:00 (Asia/Jakarta)"""
    now = datetime.now(ZoneInfo('Asia/Jakarta'))
    return now.weekday() < 5 and _COURSE_START <= now.hour < _COURSE_END

@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith('/api'):
        fwd = request.headers.get('x-forwarded-for')
        ip = fwd.split(',')[0].strip() if fwd else (request.client.host if request.client else 'unknown')
        now = time()
        window = _hits[ip]
        while window and window[0] <= now - _RATE_WINDOW:
            window.popleft()
        if len(window) >= _RATE_LIMIT:
            return JSONResponse(status_code=429, content={'error': True, 'msg': 'Rate limit exceeded. Try again later.', 'data': None})
        window.append(now)
    return await call_next(request)

_sessions = {}
_sessions_lock = threading.Lock()


def GetAuth(creds: UserCreds, request: Request):
    cache_key = hashlib.sha256(f'{creds.email}:{creds.password}'.encode()).hexdigest()
    papi = _sessions.get(cache_key)
    if papi is None:
        with _sessions_lock:
            papi = _sessions.get(cache_key)
            if papi is None:
                papi = API(creds.email, creds.password)
                papi.login()
                _sessions[cache_key] = papi
    request.state.user = papi._username
    return papi

def _ok(description, example):
    """OpenAPI 200 response with a rendered example in Swagger UI."""
    return {200: {'description': description,
                  'content': {'application/json': {'example': example}}}}

# ========
# ENDPOINT
# ========

@app.api_route("/", methods=["GET", "POST"], include_in_schema=False)
def index():
    return {"msg": "Welcome to PENS API Wrapper"}

@app.post('/api/profile', summary='Get the current user profile',
          description='Returns the authenticated student identity and active academic period.',
          responses=_ok('User profile', {
              'error': False,
              'data': {
                  'nomor': 12345,
                  'nama': 'Test Student',
                  'nrp': '3125600000',
                  'hak_akses': ['mahasiswa'],
                  'semester': 1,
                  'tahun_aktif': 2026,
                  'tahun_ajaran': '2026/2027'
              }
          }))
def api_profile(papi: API = Depends(GetAuth)):
    profile = papi.get_profile()
    return {'error': False, 'data': profile}

@app.post("/api/get-jadwal", summary='Get the class schedule',
          description='Returns the full weekly schedule for all enrolled courses this semester.',
          responses=_ok('List of schedule entries', {
              'error': False,
              'data': [
                  {
                      'id': 220817,
                      'matkul': 'Workshop Sistem Informasi Geografis',
                      'kelas': '3 STr IT',
                      'pararel': 'B',
                      'room': None,
                      'dosen': 'Dr Test Lecturer, M.Kom',
                      'nomor_dosen': 2428,
                      'day': 'Selasa',
                      'start': '13:50',
                      'end': '16:20'
                  }
              ]
          }))
def api_jadwal(papi: API = Depends(GetAuth)):
    jadwal = papi.get_jadwal()
    return {'error': False, 'data': jadwal}

@app.post("/api/get-tugas", summary='Get all tasks',
          description='Returns every task across all enrolled courses (full history, not just the latest).',
          responses=_ok('List of tasks', {
              'error': False,
              'data': [
                  {
                      'id': 220788,
                      'matkul': 'Basis Data Lanjut',
                      'title': 'Pertemuan 1_TRIGGER di ORACLE',
                      'description': 'Kerjakan latihan trigger di Oracle.',
                      'deadline': 'Senin, 31 Agustus 2026 - 23:59',
                      'submited': False
                  }
              ]
          }))
def api_tugas(papi: API = Depends(GetAuth)):
    tugas = papi.get_tugas()
    return {'error': False, 'data': tugas}

@app.post("/api/get-latest-tugas", summary='Get the latest task per course',
          description='Returns only the most recent task of each enrolled course (single batch call).',
          responses=_ok('List of latest tasks', {
              'error': False,
              'data': []
          }))
def api_tugas_terbaru(papi: API = Depends(GetAuth)):
    tugas = papi.get_latest_tugas()
    return {'error': False, 'data': tugas}

@app.post("/api/get-notif", summary='Get all notifications',
          description='Returns every ETHOL notification (materials, tasks, attendance, etc.) with read status.',
          responses=_ok('List of notifications', {
              'error': False,
              'data': [
                  {
                      'id': '96d6b727-872d-4024-8d99-a99271fd1e0b-28775',
                      'keterangan': 'Materi baru dengan judul Pertemuan 1_TRIGGER di ORACLE telah ditambahkan...',
                      'is_read': False,
                      'notif_type': 'MATERI',
                      'related_data': '16768',
                      'url_web': '/matakuliah/220788/materi',
                      'created_at': '2026-08-24T04:53:40.000Z',
                      'time_since': '1 hari yang lalu',
                      'created_at_format': 'Senin, 24 Agustus 2026 - 11:53'
                  }
              ]
          }))
def api_notifikasi(papi: API = Depends(GetAuth)):
    notif = papi.get_notification()
    return {'error': False, 'data': notif}

@app.post("/api/presensi", summary='Get the Online-MIS attendance recap',
          description='Returns weekly attendance status per course from Online-MIS. '
                      'Each week is `true` (attended), `false` (absent) or `null` (no data).',
          responses=_ok('Attendance recap per course', {
              'error': False,
              'data': {
                  'presensi': [
                      {
                          'matkul': 'Etika Profesi dan Komunikasi',
                          'week': [None, None, None, None, None, None, None, None,
                                   None, None, None, None, None, None, None, None]
                      }
                  ]
              }
          }))
def api_presensi(papi: API = Depends(GetAuth)):
    presensi = papi.get_presensi()
    return {'error': False, 'data': presensi}

@app.post("/api/absen", summary='Check open attendance and submit it',
          description='Scans all enrolled courses for currently open attendance sessions and '
                      'submits attendance for any that are not yet recorded. '
                      'Skips the check entirely outside course hours (Mon-Fri, 06:00-18:00 WIB).',
          responses=_ok('Attendance processing result', {
              'error': False,
              'data': {
                  'absen': [],
                  'details': 'no open attendance'
              }
          }))
def api_absen(papi: API = Depends(GetAuth)):
    if not _is_course_hours():
        return {'error': False, 'data': {'absen': [], 'details': 'no open attendance'}}
    data_absen = papi.absen()
    return {'error': False, 'data': data_absen}

# Local development
if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=1212, access_log=False)
