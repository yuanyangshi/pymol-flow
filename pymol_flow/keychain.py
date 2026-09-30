"""Store an API key in Windows Credential Manager."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import getpass


SERVICE = "io.pymolflow.credentials"
ACCOUNT = getpass.getuser()


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.c_char_p),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2

_advapi32 = ctypes.windll.advapi32
_CredWriteW = _advapi32.CredWriteW
_CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
_CredWriteW.restype = wintypes.BOOL

_CredReadW = _advapi32.CredReadW
_CredReadW.argtypes = [
    wintypes.LPWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.POINTER(ctypes.POINTER(_CREDENTIAL)),
]
_CredReadW.restype = wintypes.BOOL

_CredDeleteW = _advapi32.CredDeleteW
_CredDeleteW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
_CredDeleteW.restype = wintypes.BOOL

_CredFree = _advapi32.CredFree
_CredFree.argtypes = [ctypes.c_void_p]
_CredFree.restype = None


def credential_store_name() -> str:
    """Return the human-readable credential store name."""
    return "Windows Credential Manager"


def _read_from_target(target: str) -> str:
    try:
        pcred = ctypes.POINTER(_CREDENTIAL)()
        if not _CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
            return ""
        try:
            raw = ctypes.string_at(
                pcred.contents.CredentialBlob, pcred.contents.CredentialBlobSize
            )
            return raw.decode("utf-8", "replace").strip()
        finally:
            _CredFree(pcred)
    except Exception:
        return ""


def read_api_key() -> str:
    return _read_from_target(SERVICE)


def save_api_key(value: str) -> None:
    key = value.strip()
    if not key:
        raise ValueError("Enter an API key before saving.")

    blob = key.encode("utf-8")
    cred = _CREDENTIAL(
        Flags=0,
        Type=_CRED_TYPE_GENERIC,
        TargetName=SERVICE,
        Comment="PyMOL Flow API Key",
        CredentialBlobSize=len(blob),
        CredentialBlob=blob,
        Persist=_CRED_PERSIST_LOCAL_MACHINE,
        UserName=ACCOUNT,
    )
    if not _CredWriteW(ctypes.byref(cred), 0):
        code = ctypes.GetLastError()
        raise RuntimeError(
            f"Could not save the API key in Windows Credential Manager (error code {code})."
        )


def delete_api_key() -> None:
    try:
        _CredDeleteW(SERVICE, _CRED_TYPE_GENERIC, 0)
    except Exception:
        pass
