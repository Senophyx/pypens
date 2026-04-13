"""
# PyPENS
Unofficial Python API Wrapper for Politeknik Elektronika Negeri Surabaya (PENS).

## Quick Example

```python
from pypens import API, APIError

try:
    # Login using NETID
    client = API("email@dep.student.pens.ac.id", "passwordhere")
    client.login() # Must!

    # Get some data
    jadwal = client.get_jadwal()
    presensi = client.get_presensi()

except APIError as e:
    print(f"Error: {e}")
```
"""


from .core import API
from .exceptions import APIError

__title__ = "PyPENS"
__authors__ = "Senophyx"
__license__ = "MIT License"
__copyright__ = "Copyright 2026 Senophyx"