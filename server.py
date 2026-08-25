import hashlib

from pypens import API, APIError
import uvicorn
import logging
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

app = FastAPI(title='PENS API Wrapper')
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

# =============================

class UserCreds(BaseModel):
    email: str
    password: str

# ponytail: global session cache, per-user lock if concurrency matters
_sessions = {}

def GetAuth(creds: UserCreds, request: Request):
    cache_key = hashlib.sha256(f'{creds.email}:{creds.password}'.encode()).hexdigest()
    papi = _sessions.get(cache_key)
    if papi is None:
        papi = API(creds.email, creds.password)
        papi.login()
        _sessions[cache_key] = papi
    request.state.user = papi._username
    return papi

# ========
# ENDPOINT
# ========

@app.api_route("/", methods=["GET", "POST"], include_in_schema=False)
def index():
    return {"msg": "Welcome to PENS API Wrapper"}

@app.post('/api/profile')
def api_profile(papi: API = Depends(GetAuth)):
    profile = papi.get_profile()
    return {'error': False, 'data': profile}

@app.post("/api/get-jadwal")
def api_jadwal(papi: API = Depends(GetAuth)):
    jadwal = papi.get_jadwal()
    return {'error': False, 'data': jadwal}

@app.post("/api/get-tugas")
def api_tugas(papi: API = Depends(GetAuth)):
    tugas = papi.get_tugas()
    return {'error': False, 'data': tugas}

@app.post("/api/get-latest-tugas")
def api_tugas_terbaru(papi: API = Depends(GetAuth)):
    tugas = papi.get_latest_tugas()
    return {'error': False, 'data': tugas}

@app.post("/api/get-notif")
def api_notifikasi(papi: API = Depends(GetAuth)):
    notif = papi.get_notification()
    return {'error': False, 'data': notif}

@app.post("/api/presensi")
def api_presensi(papi: API = Depends(GetAuth)):
    presensi = papi.get_presensi()
    return {'error': False, 'data': presensi}

@app.post("/api/absen")
def api_absen(papi: API = Depends(GetAuth)):
    data_absen = papi.absen()
    return {'error': False, 'data': data_absen}

# Local development
if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=1212, access_log=False)
