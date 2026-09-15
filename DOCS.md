# PyPENS

Unofficial Python API wrapper for Politeknik Elektronika Negeri Surabaya (PENS).
It talks to two systems:

- **ETHOL** (`ethol.pens.ac.id`): e-learning. Schedule, tasks, notifications, attendance.
- **Online-MIS** (`online.mis.pens.ac.id`): academic info system. Attendance recap.

An optional FastAPI server (`server.py`) exposes the whole SDK over HTTP.

```
This Project under MIT License
Copyright (c) 2026 Senophyx
```

---

## Installation

The package is not on PyPI yet, install it straight from the repository:

```bash
pip install "pypens @ git+https://github.com/Senophyx/pypens.git"
```

Or clone it and let [uv](https://docs.astral.sh/uv/) handle the environment:

```bash
git clone https://github.com/Senophyx/pypens
cd pypens
uv sync
```

> Requires Python 3.9+. Dependencies: `requests`, `beautifulsoup4`.

### Server extra

The REST server is optional. Its dependencies (`fastapi`, `uvicorn`, `pydantic`) live in the `server` extra, so the plain install above does not include them.

```bash
# straight from the repository
pip install "pypens[server] @ git+https://github.com/Senophyx/pypens.git"

# from a clone, with uv
uv sync --extra server
```

After that `python3 server.py` or `uvicorn server:app` works. Without the extra, importing `server.py` fails on `fastapi`.

---

## Project Layout

```
pypens/
  __init__.py    Package exports (API, APIError) and metadata
  core.py        API class, logging adapter, HTTP request core
  auth.py        AuthHandler: CAS SSO login, session cache, config
  ethol.py       EtholHandler: schedule, tasks, notifications, absen
  mis.py         MisHandler: Online-MIS attendance recap
  exceptions.py  APIError
server.py        FastAPI REST wrapper (optional)
tests/           Live tests against the real API
users/           Session cache files, one JSON per account
compose.yaml     Docker deployment for the server
```

---

## Quick Start

1. Make sure `pypens` is installed.
2. Import the package.
   ```py
   from pypens import API, APIError
   ```
3. Create a client with your PENS NetID. Credentials are only used in memory, sessions are cached on disk.
   ```py
   client = API("test@it.student.pens.ac.id", "password")
   ```
4. Login. This is mandatory before any other call.
   ```py
   client.login()
   ```
5. Call any getter.
   ```py
   jadwal = client.get_jadwal()
   presensi = client.get_presensi()
   ```
6. Wrap everything in a `try` block, every failure raises `APIError`.
   ```py
   from pypens import API, APIError

   try:
       client = API("test@it.student.pens.ac.id", "password")
       client.login()

       for mk in client.get_jadwal():
           print(mk["matkul"], mk["day"], mk["start"], "-", mk["end"])

   except APIError as e:
       print(f"Error: {e}")
   ```

---

## How It Works

### Authentication flow (ETHOL, CAS SSO)

`login()` follows the same flow as the official web frontend:

1. `GET /api/auth/cas-redirect` returns a `302` to the PENS CAS login page.
2. The CAS page (`login.pens.ac.id`) is parsed for the `lt` token, `_eventId`, and form `action`.
3. Credentials are `POST`ed to the form action. Success means a `302` with a `Location` containing the service ticket. Wrong credentials return `200` with an error page instead.
4. `GET` on the ticket URL sets two cookies on the session: `token` (JWT, 900s TTL) and `refresh_token` (7 days TTL).
5. `GET /auth/cas` loads the app shell, then `GET /api/auth/validasi-token` confirms the token works.

All later requests are authenticated by the `token` cookie. When a request returns `401`, the client calls `POST /api/auth/refresh` once and retries the request. If the refresh fails, you need to `login()` again.

### Session cache

Every account gets a JSON file in `users/` named `{username}.{depart}.json`, for example `test@it.student.pens.ac.id` becomes `users/test.it.json`. The department comes from the first label of the email domain, so `test@it.student.pens.ac.id` and `test@me.student.pens.ac.id` are two separate accounts.

```json
{
    "hash": "sha256(email:password)",
    "token": "eyJhbGciOi...",
    "refresh_token": "eyJhbGciOi...",
    "cookies": {
        "token": "eyJhbGciOi...",
        "refresh_token": "eyJhbGciOi..."
    },
    "last_login": "2026-08-24 11:53:40"
}
```

- `hash` ties the file to the exact email and password. Changing the password invalidates the cache.
- On `login()`, the cache is loaded, restored into the session cookie jar, and validated with `validasi-token`. A valid session skips the whole CAS dance.
- If the access token expired, `refresh_token` renews it without a password.

---

## API Reference

### `API`

```python
class API(AuthHandler, EtholHandler, MisHandler):
    def __init__(...): -> None
```

The single public class. It combines the three handlers, so every method below lives on the same object.

#### `API.__init__`

Creates the HTTP session, the per user logger, and the session cache path.

```py
client = API("test@it.student.pens.ac.id", "password")
```

Parameters:

- **email** *(str)*: PENS NetID email, e.g. `test@it.student.pens.ac.id`.
- **password** *(str)*: PENS NetID password.
- **users_dir** *(str, default: `"users"`)*: folder for session cache files. Created automatically if missing.
- **debug** *(bool, default: `False`)*: if `True`, sets the log level to `DEBUG` and prints every HTTP step.

Variables (all private, read them if you need introspection):

- **_email** *(str)*: the email passed in.
- **_password** *(str)*: the password passed in.
- **_token** *(str | None)*: current ETHOL JWT. Set after login, `None` before.
- **_tahun** *(int | None)*: active academic year, e.g. `2026`. Filled by `get_config()`.
- **_semester** *(int | None)*: active semester, e.g. `1`.
- **_tahun_ajaran** *(str | None)*: academic year label, e.g. `"2026/2027"`.
- **_menit_per_jam** *(int | None)*: minutes per class hour, from the server config.
- **_users_dir** *(str)*: session cache folder.
- **_username** *(str)*: email prefix, used for logging.
- **_depart** *(str)*: first label of the email domain (`it`, `me`, ...), part of the cache filename.
- **_session_file** *(str)*: full path to the cache file, `{users_dir}/{username}.{depart}.json`.
- **_user_hash** *(str)*: `sha256("{email}:{password}")`, the cache ownership check.
- **_log** *(LoggerAdapter)*: logger that prefixes every line with the username.
- **_session** *(requests.Session)*: the shared HTTP session (headers + cookies).
- **_refresh_lock** *(threading.Lock)*: prevents concurrent token refreshes from worker threads.

#### `API.login`

```python
def login(): -> bool
```

Logs in via CAS SSO, or reuses a valid cached session. Returns `True` on success.

```py
client = API("test@it.student.pens.ac.id", "password")
client.login()  # True
```

Notes:

- If the cache is valid, no password is sent anywhere. The session file is touched (`last_login` updated) and config is loaded if missing.
- If the cached token is expired but `refresh_token` is alive, the token is renewed silently.
- Raises `APIError("Unable to find CAS url")` when the redirect is missing, `APIError("Invalid email or password")` on a bad login, and `APIError("Unable to obtain token")` when the ticket exchange fails.
- Calling `login()` twice is safe and cheap, the second call hits the cache.

#### `API.get_config`

```python
def get_config(): -> bool
```

Fetches the active academic period. Called automatically by every getter that needs it.

```py
client.get_config()
print(client._tahun, client._semester, client._tahun_ajaran)
# 2026 1 2026/2027
```

Variables it fills: `_tahun` (`tahun_aktif`), `_semester` (`semester_aktif`), `_tahun_ajaran` (`tahun_ajaran_aktif`), `_menit_per_jam` (`menit_per_jam`).

Raises `APIError("Invalid session token")` when not logged in, `APIError("Unable to load config")` when the server rejects the call.

#### `API._request`

```python
def _request(method, url, **kwargs): -> requests.Response
```

The shared request core used by every ETHOL call. Defaults `timeout` to 10 seconds.

- On `401` for any URL outside `/api/auth/`, it calls `_refresh()` and retries the request once.
- `requests.exceptions.Timeout` becomes `APIError("Server Timeout")`.
- `requests.exceptions.SSLError` becomes `APIError("SSL Error")`.
- Any other `RequestException` becomes `APIError("Internal Error")`.

#### `API._refresh`

```python
def _refresh(): -> bool
```

Renews the access token with `POST /api/auth/refresh`, then saves the session. Returns `False` when the refresh token is dead, which tells the caller a full `login()` is needed.

#### `API._clone_session`

```python
def _clone_session(): -> requests.Session
```

Creates an independent `requests.Session` with copied headers and cookies. Used by threaded calls so two threads never share a connection pool.

#### `API._thread_request`

```python
def _thread_request(method, url, session, **kwargs): -> requests.Response | None
```

Request wrapper for worker threads. Retries up to 5 times on network errors with a `0.5 * attempt` second backoff, refreshes the token once on `401` (guarded by `_refresh_lock`), and returns `None` when every attempt fails.

#### `API._load_session`

```python
def _load_session(): -> bool
```

Reads `_session_file`, checks the hash, restores `token` and `refresh_token` cookies, and validates them with `GET /api/auth/validasi-token`. Returns `True` when the session is usable, `False` on hash mismatch, expiry without a working refresh, or any read error.

#### `API._save_session`

```python
def _save_session(): -> None
```

Writes `hash`, `token`, `refresh_token`, `cookies`, and `last_login` to the cache file. Errors are logged, never raised.

---

### Profile

#### `API.get_profile`

```python
def get_profile(): -> dict
```

Returns the authenticated identity plus the active period.

```py
profile = client.get_profile()
print(profile)
```

```py
{
    "nomor": 12345,
    "nama": "Test Student",
    "nrp": "3125600000",
    "hak_akses": ["mahasiswa"],
    "semester": 1,
    "tahun_aktif": 2026,
    "tahun_ajaran": "2026/2027"
}
```

Keys: `nomor` (internal id), `nama`, `nrp` (from `nipnrp`), `hak_akses` (list, from `hakAkses`), `semester`, `tahun_aktif`, `tahun_ajaran`.

Raises `APIError("Invalid session token")` without a token, `APIError("Ethol server Error (code)")` on a non-200.

---

### Schedule

#### `API.get_jadwal`

```python
def get_jadwal(): -> list[dict]
```

Returns the full weekly schedule. It makes two calls under the hood: `GET /api/kuliah` for the course list, then `POST /api/kuliah/hari-kuliah-in` for the day and time of each course. Both lists are merged by course id.

```py
for mk in client.get_jadwal():
    print(f"{mk['day']} {mk['start']}-{mk['end']} | {mk['matkul']} ({mk['kelas']}) in {mk['room']}")
```

```py
[
    {
        "id": 220817,
        "matkul": "Workshop Sistem Informasi Geografis",
        "kelas": "3 STr IT",
        "pararel": "B",
        "room": None,
        "dosen": "Dr Test Lecturer, M.Kom",
        "nomor_dosen": 2428,
        "day": "Selasa",
        "start": "13:50",
        "end": "16:20"
    }
]
```

Keys: `id` (course number), `matkul`, `kelas`, `pararel`, `room` (can be `None` for online classes), `dosen` (title prefix and suffix merged in), `nomor_dosen`, `day`, `start`, `end`.

Raises `APIError("Invalid session token")` without a token, `APIError("Server Error (code)")` on a failed call.

---

### Tasks

#### `API.get_tugas`

```python
def get_tugas(): -> list[dict]
```

Returns every task across all courses (full history). One request per course, fanned out over a `ThreadPoolExecutor` with 10 workers.

```py
tugas = client.get_tugas()
belum = [t for t in tugas if not t["submited"]]
print(f"{len(belum)} tugas belum dikumpulkan")
```

```py
[
    {
        "id": 220788,
        "matkul": "Basis Data Lanjut",
        "title": "Pertemuan 1_TRIGGER di ORACLE",
        "description": "Kerjakan latihan trigger di Oracle.",
        "deadline": "Senin, 31 Agustus 2026 - 23:59",
        "submited": False
    }
]
```

Keys: `id` (course number, not task number), `matkul`, `title`, `description`, `deadline` (Indonesian format when available), `submited` (`True` when the server reports a submission time, note the single `t`).

A course that fails to load contributes an empty list instead of killing the whole call.

#### `API._fetch_tugas`

```python
def _fetch_tugas(mk): -> list[dict]
```

Worker used by `get_tugas()`. Takes one course dict, calls `GET /api/tugas?kuliah=&jenisSchema=` through `_thread_request`, and maps the raw tasks to the shape above. Returns `[]` when the request fails.

#### `API.get_latest_tugas`

```python
def get_latest_tugas(): -> list[dict]
```

Returns only the latest task per course, in a single batch call (`POST /api/tugas/tugas-terakhir-mahasiswa`). Much cheaper than `get_tugas()` when you only care about what is currently due.

```py
for t in client.get_latest_tugas():
    print(t)
```

Returns the raw server items with `None` entries filtered out. The response shape depends on the server payload.

---

### Notifications

#### `API.get_notification`

```python
def get_notification(): -> list[dict]
```

Returns every ETHOL notification with its read status and a normalized type.

```py
notifs = client.get_notification()
unread = [n for n in notifs if not n["is_read"]]
print(f"{len(unread)} notifikasi belum dibaca")
```

```py
[
    {
        "id": "96d6b727-872d-4024-8d99-a99271fd1e0b-28775",
        "keterangan": "Materi baru dengan judul Pertemuan 1_TRIGGER di ORACLE telah ditambahkan...",
        "is_read": False,
        "notif_type": "MATERI",
        "related_data": "16768",
        "url_web": "/matakuliah/220788/materi",
        "created_at": "2026-08-24T04:53:40.000Z",
        "time_since": "1 hari yang lalu",
        "created_at_format": "Senin, 24 Agustus 2026 - 11:53"
    }
]
```

Keys: `id` (`idNotifikasi`), `keterangan`, `is_read` (`True` when `status == "2"`), `notif_type` (prefix of `kodeNotifikasi` before the first `-`, e.g. `MATERI`, `TUGAS`, `PRESENSI`, `PENGUMUMAN`), `related_data` (`dataTerkait`, usually a course id), `url_web`, `created_at`, `time_since` (server rendered Indonesian string), `created_at_format` (Indonesian formatted timestamp).

#### `API.get_unread_notification_count`

```python
def get_unread_notification_count(): -> int
```

Returns just the unread count. One lightweight request, useful for polling a badge.

```py
print(client.get_unread_notification_count())  # 3
```

#### `API.baca_notifikasi`

```python
def baca_notifikasi(id_notifikasi: str): -> bool
```

Marks one notification as read (`PUT /api/notifikasi/mahasiswa-baca-notif`).

```py
client.baca_notifikasi("96d6b727-872d-4024-8d99-a99271fd1e0b-28775")  # True
```

Raises `APIError("Server Error (code)")` when the server rejects the id.

---

### Attendance

#### `API.absen`

```python
def absen(): -> dict
```

Checks for open attendance sessions and submits attendance for any course that is not recorded yet.

Flow:

1. The student id is decoded from the JWT payload (`nomor`).
2. Notifications are fetched and filtered to `kodeNotifikasi == "PRESENSI-KULIAH"`.
3. If there is no attendance notification, it returns immediately with an empty result. This is the fast idle path: one request when nothing is happening.
4. Notifications are deduplicated per course (newest wins) and anything older than 24 hours is dropped, so old sessions do not trigger repeated checks.
5. For each remaining notification, `GET /api/presensi/aktif-kuliah` looks for a session with `open` truthy.
6. `GET /api/presensi/riwayat` checks whether this session key is already recorded.
7. If not recorded, `POST /api/presensi/mahasiswa` submits `{kuliah, jenis_schema, mahasiswa, key, kuliah_asal}` and the result is verified with one more `riwayat` call.

```py
hasil = client.absen()
print(hasil)
```

```py
{
    "absen": [
        {
            "matkul": "Basis Data Lanjut",
            "submitted": True,
            "details": "Presensi berhasil",
            "verifikasi": {
                "nomor": 98765,
                "tanggal": "2026-08-24",
                "waktu_indonesia": "11:53"
            }
        },
        {
            "matkul": "Etika Profesi dan Komunikasi",
            "submitted": False,
            "details": "already attended"
        }
    ],
    "details": "1 matkul attended"
}
```

Keys: `absen` is a list of per course results with `matkul`, `submitted` (bool), `details` (server message or a local note), and `verifikasi` (present only on a fresh successful submit, holds `nomor`, `tanggal`, `waktu_indonesia`). The top level `details` summarizes how many courses were attended.

When nothing is open, the result is `{"absen": [], "details": "no open attendance"}`.

#### `API._cek_notif`

```python
def _cek_notif(notif): -> dict | None
```

Helper inside `absen()`. Splits `dataTerkait` into `kuliah` and `jenis_schema`, queries `aktif-kuliah`, and returns the open session as `{"kuliah", "jenis_schema", "key", "matkul", "kuliah_asal"}`. Returns `None` when the notification does not map to an open session.

#### `API.get_presensi`

```python
def get_presensi(): -> dict
```

Returns the weekly attendance recap from Online-MIS. This uses a separate session and a separate CAS login, independent from ETHOL.

```py
presensi = client.get_presensi()
for mk in presensi["presensi"]:
    hadir = sum(1 for w in mk["week"] if w)
    print(f"{mk['matkul']}: {hadir}/16")
```

```py
{
    "presensi": [
        {
            "matkul": "Etika Profesi dan Komunikasi",
            "week": [None, None, None, None, None, None, None, None,
                     None, None, None, None, None, None, None, None]
        }
    ]
}
```

`week` always has 16 entries, oldest first. Values:

- `True`: attended, HTML cell was `H` or `HH`.
- `False`: absent, any other non-empty marker.
- `None`: no data, HTML cell was `-`.

Failure modes return `{"presensi": []}` for a rejected MIS login, a missing form, or a missing table. A network error raises `APIError("Error fetching OnlineMIS")`.

---

## Server (REST API)

`server.py` wraps the SDK in a FastAPI app. Every endpoint takes the same JSON body with credentials and returns the envelope `{"error": false, "data": ...}`.

### Run it

```bash
# local, listens on port 1212
python3 server.py

# or via uvicorn
uvicorn server:app --host 0.0.0.0 --port 8000
```

Swagger UI is available at `/docs`, OpenAPI JSON at `/openapi.json`.

### Docker

```bash
docker compose up -d
```

`compose.yaml` maps host port `2003` to container `8000`, mounts `server.py`, `pypens/`, and `users/` for live reload, and sets `TZ=Asia/Jakarta`. The umami analytics variables are declared there too, disabled by default.

### Auth model

Credentials are sent in the body of every request and never stored. Sessions are cached in memory per user, keyed by `sha256(email:password)`, under a double checked lock so concurrent requests for the same user share one `API` instance.

### Variables and helpers

- **_RATE_LIMIT** *(int, `20`)*: max requests per IP per window.
- **_RATE_WINDOW** *(float, `60.0`)*: rate limit window in seconds.
- **_hits** *(defaultdict of deque)*: per IP request timestamps, pruned on each hit.
- **_COURSE_START** *(int, `6`)*, **_COURSE_END** *(int, `18`)*: course hours used to gate `/api/absen`.
- **_sessions** *(dict)*: credential hash to live `API` instance.
- **_sessions_lock** *(threading.Lock)*: guards `_sessions` creation.
- **UserCreds** *(pydantic model)*: request body with `email` and `password`.
- **GetAuth** *(dependency)*: resolves or creates the cached `API` for the request, calls `login()` on first use, and stores the username on `request.state.user`.
- **_is_course_hours()**: `True` when the current Asia/Jakarta time is Mon-Fri between 06:00 and 18:00.
- **_ok(description, example)**: builds a `200` OpenAPI response with a rendered example for Swagger UI.

### Middleware

- **rate_limit**: applies to paths starting with `/api`. Reads `X-Forwarded-For` first, then the socket IP. Over the limit returns `429` with `{"error": true, "msg": "Rate limit exceeded. Try again later.", "data": null}`.
- **custom_logging**: logs `[user] METHOD /path - status` after each response. Falls back to `guest` when no user was resolved.
- **analytics**: sends a request event to a self hosted umami instance. Disabled unless configured, see below.

### Analytics (umami)

The server can report its own traffic to a self hosted [umami](https://umami.is) instance, so you can see how many users hit the API and which endpoints they use. It is a server side integration: the tracking script is not used, the server posts events to the umami API directly.

Disabled by default. All three variables must be set for anything to be sent:

| Variable | Default | Description |
|----------|---------|-------------|
| `UMAMI_ENABLE` | `false` | Turns the feature on. Only the literal value `true` (case insensitive) enables it. |
| `UMAMI_URL` | empty | Base URL of the umami instance, e.g. `https://analytics.example.com`. A trailing slash is stripped. |
| `UMAMI_WEB_ID` | empty | Website ID (UUID) of the umami website entry to report to. |

```yaml
# compose.yaml
environment:
  - UMAMI_ENABLE=true
  - UMAMI_URL=https://analytics.example.com
  - UMAMI_WEB_ID=00000000-0000-0000-0000-000000000000
```

What gets sent, for every request:

- One pageview. `url` is the endpoint path, so the umami **Pages** report becomes a per endpoint breakdown. `title` is `"METHOD /path"`.
- One extra `api-error` event when the status is `400` or higher, with `endpoint`, `method`, `status`, and the real client user agent under `client`. These show up in the umami **Events** report.

Payload fields:

| Field | Value |
|-------|-------|
| `website` | `UMAMI_WEB_ID` |
| `hostname` | `Host` header, port stripped |
| `url` | request path, e.g. `/api/get-jadwal` |
| `title` | `"METHOD /path"`, e.g. `POST /api/get-jadwal` |
| `id` | username resolved by `GetAuth`, or `guest` when the request never authenticated. This is the umami distinct ID. |
| `ip` | first entry of `X-Forwarded-For`, else the socket IP |
| `userAgent` | fixed browser like string, see below |

Notes:

- **The user agent header is deliberately a browser string.** Umami drops anything that looks like a bot, and `python-requests`, `httpx`, `curl`, and even `PENS-API/1.0` all match its bot patterns. Sending the client agent as is would silently drop most events. The real client agent is preserved in the `api-error` event data instead.
- **`id` is what makes visitors meaningful.** Because the distinct ID is the username, umami keeps one stable session per user, so unique visitors equals unique users. Location, device, and browser are recorded on the user's first request and reused after that, since umami does not rewrite an existing session.
- **No credentials are sent.** Only the username, the endpoint path, the status code, and the client user agent leave the server.
- **Fire and forget.** Events are sent from a daemon thread to `POST {UMAMI_URL}/api/batch` with a 3 second timeout. A failure is logged as `umami: ...` and never affects the response the user gets.
- The middleware is declared after `rate_limit`, which makes it the outermost one, so requests rejected with `429` are counted too, and the status code seen by umami is the final one.
- Every path is tracked, including `/`, `/docs`, and `/openapi.json`. Requests that fail before a username is resolved are attributed to `guest`.
- **`ip` needs a reverse proxy to be meaningful.** `X-Forwarded-For` only exists when something in front sets it. Behind Cloudflare Tunnel it carries the visitor IP, which is what production uses. When the container port is exposed directly, the fallback is a private Docker address that umami ignores, so geolocation stays empty.

### Exception handling

- **APIError**: `401` with the exception message. Used for login failures and invalid sessions.
- **StarletteHTTPException**: original status code, friendly messages for `404` (`Endpoint not found`) and `405` (`Method not allowed`).
- **Any other exception**: `500` with `{"error": true, "msg": "internal error", "data": null}` and a full traceback in the server log.

### Endpoints

All endpoints are `POST` and require the `UserCreds` body.

#### `POST /api/profile`

Returns `get_profile()` output.

```bash
curl -s http://localhost:2003/api/profile \
  -H 'Content-Type: application/json' \
  -d '{"email": "test@it.student.pens.ac.id", "password": "password"}'
```

#### `POST /api/get-jadwal`

Returns `get_jadwal()` output.

#### `POST /api/get-tugas`

Returns `get_tugas()` output, the full task history.

#### `POST /api/get-latest-tugas`

Returns `get_latest_tugas()` output, the latest task per course.

#### `POST /api/get-notif`

Returns `get_notification()` output.

#### `POST /api/presensi`

Returns `get_presensi()` output from Online-MIS.

#### `POST /api/absen`

Returns `absen()` output. Outside course hours the SDK is not called at all, the endpoint answers `{"absen": [], "details": "no open attendance"}` immediately.

#### `GET|POST /`

Hidden health endpoint, returns `{"msg": "Welcome to PENS API Wrapper"}`.

---

## Exceptions

| Exception | Description |
|-----------|-------------|
| `APIError(message)` | Every failure in the package. Subclass of `Exception`. |

Common messages:

| Message | Cause |
|---------|-------|
| `Invalid session token` | A getter was called before `login()`. |
| `Invalid email or password` | CAS rejected the credentials. |
| `Unable to find CAS url` | The CAS redirect or login form could not be parsed. |
| `Unable to obtain token` | Ticket exchange or token validation failed. |
| `Unable to load config` | `/api/auth/config` did not return `200`. |
| `Server Error (code)` | An ETHOL data endpoint failed. |
| `Server Timeout` | Request exceeded the 10 second timeout. |
| `SSL Error` | TLS handshake failed. |
| `Internal Error` | Any other network level failure. |
| `Unable to extract mahasiswa_id` | JWT payload could not be decoded in `absen()`. |
| `Error fetching OnlineMIS` | Network failure while talking to Online-MIS. |

---

## Testing

Live tests hit the real API. Provide credentials through environment variables or `tests/test.env`:

```bash
export PYPENS_EMAIL=test@it.student.pens.ac.id
export PYPENS_PASSWORD=password
python3 -m unittest discover -s tests -v
```

`tests/test.env` format:

```
EMAIL=test@it.student.pens.ac.id
PASSWORD=password
```

Sessions for tests are cached in `tests/users/`, which is gitignored. The suite prints every raw response so you can inspect the actual shapes.

---

## Troubleshooting

- **`Invalid session token` on the first call**: `login()` was not called, or it returned `False`. Always check the login result.
- **Login suddenly fails after working before**: the password changed, so the cached session hash no longer matches. Delete `users/{username}.{depart}.json` and log in again.
- **`401` in the middle of a long job**: the access token expired and the refresh token is dead. Call `login()` again.
- **`absen()` returns `no open attendance` during class**: the notification may be older than 24 hours, or the lecturer has not opened the session on ETHOL yet.
- **`get_presensi()` returns an empty list**: the Online-MIS login failed or the page layout changed. Run with `debug=True` to see which step broke.
- **Server returns `429`**: rate limit hit, 20 requests per minute per IP.
- **No events in the umami dashboard**: check that `UMAMI_ENABLE=true` and both `UMAMI_URL` and `UMAMI_WEB_ID` are set. Then check the container log for `umami: ...` warnings, which mean the umami instance could not be reached.
- **Server returns `401` with `internal error` style envelope**: that is the `APIError` handler, the message carries the real cause.
- **Verbose logging**: `API(email, password, debug=True)`.

---

## FAQ

**Q: Do I need to store my password?**
A: No. The password is only used during login. Sessions are cached in `users/{username}.{depart}.json` and reused.

**Q: Is this official?**
A: No. It is an unofficial wrapper. Behavior can change whenever PENS updates ETHOL or Online-MIS.

**Q: Why are some schedule `room` values `None`?**
A: Online classes have no room assigned by the server.

**Q: Does `absen()` submit attendance automatically?**
A: Yes, when a session is open and not yet recorded. Outside course hours the server endpoint skips the check entirely.

**Q: Can I run this on a server without a browser?**
A: Yes. Both login flows are pure HTTP, no browser or headless engine needed.

**Q: Does the server send my password to the analytics service?**
A: No. The analytics middleware only sends the username, the endpoint path, the status code, and the client user agent. It is off by default.

---

## Links

- [GitHub](https://github.com/Senophyx/pypens)

## Licence

```
MIT License
Copyright (c) 2026 Senophyx
```
