"""Safe, versioned container for AGRV2K runtime mapping databases.

AGDB files are a small binary header followed by deterministic, zlib-compressed
JSON.  They contain data only: loading never executes constructors or imports,
unlike pickle.  Tuple and frozenset identity is retained by explicit tags.
"""
from __future__ import annotations

import json
import os
import struct
import sys
# zlib is imported lazily. nextpnr embeds its own Python, and on Windows with
# oss-cad-suite on PATH the interpreter cannot load the zlib extension -- the
# arch script then dies with "DLL load failed while importing zlib" before it
# has read a single wire, even though building the architecture graph never
# touches an .agdb file. Importing it at first use keeps the ordinary CLI
# working there.
zlib = None
_zlib_dll_dir = None


def _zlib():
    global zlib, _zlib_dll_dir
    if zlib is None:
        try:
            import zlib as _module
        except ImportError:
            # Python 3.8+ no longer searches PATH for extension-module DLL
            # dependencies.  oss-cad-suite's nextpnr embeds Python and keeps
            # zlib1.dll in <suite>/lib, so the zlib extension is discoverable
            # but cannot load until that directory is registered explicitly.
            # sys.prefix is the suite root in the embedded interpreter.  Keep
            # the handle alive: closing it removes the directory again.
            dll_dir = os.path.join(sys.prefix, "lib")
            if os.name != "nt" or not hasattr(os, "add_dll_directory") \
                    or not os.path.isdir(dll_dir):
                raise
            _zlib_dll_dir = os.add_dll_directory(dll_dir)
            import zlib as _module
        zlib = _module
    return zlib


MAGIC = b"AGDB\x00"
SCHEMA_VERSION = 1
MAX_UNCOMPRESSED = 512 * 1024 * 1024


class ChipDBError(ValueError):
    pass


def _encode(value):
    if isinstance(value, tuple):
        return ["T"] + [_encode(item) for item in value]
    if isinstance(value, frozenset):
        encoded = [_encode(item) for item in value]
        encoded.sort(key=lambda item: json.dumps(item, separators=(",", ":"), sort_keys=True))
        return ["F"] + encoded
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError("AGDB values must be scalar, tuple, or frozenset; got %s" % type(value).__name__)


def _decode(value):
    if isinstance(value, list):
        if not value or value[0] not in ("T", "F"):
            raise ChipDBError("invalid tagged AGDB sequence")
        items = [_decode(item) for item in value[1:]]
        return tuple(items) if value[0] == "T" else frozenset(items)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ChipDBError("invalid AGDB value type")


def dumps(datasets, *, metadata=None):
    payload = {
        "schema": SCHEMA_VERSION,
        "metadata": metadata or {},
        "datasets": {
            name: [[_encode(key), _encode(value)] for key, value in sorted(
                mapping.items(), key=lambda item: repr(item[0])
            )]
            for name, mapping in sorted(datasets.items())
        },
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    compressed = _zlib().compress(encoded, 9)
    return MAGIC + struct.pack(">HI", SCHEMA_VERSION, len(encoded)) + compressed


def loads(data, *, expected=None):
    header_size = len(MAGIC) + 6
    if len(data) < header_size or data[:len(MAGIC)] != MAGIC:
        raise ChipDBError("not an AGDB file")
    schema, raw_length = struct.unpack(">HI", data[len(MAGIC):header_size])
    if schema != SCHEMA_VERSION:
        raise ChipDBError("unsupported AGDB schema %d" % schema)
    if raw_length > MAX_UNCOMPRESSED:
        raise ChipDBError("AGDB uncompressed length exceeds safety limit")
    decoder = _zlib().decompressobj()
    try:
        # The envelope length is authenticated structurally before allocating
        # its output. This also rejects a compressed bomb whose header lies
        # about the decoded size.
        raw = decoder.decompress(data[header_size:], raw_length + 1)
        if decoder.unconsumed_tail or len(raw) > raw_length:
            raise ChipDBError("AGDB length mismatch")
        raw += decoder.flush()
    except _zlib().error as exc:
        raise ChipDBError("invalid AGDB compressed payload") from exc
    if not decoder.eof or decoder.unused_data or len(raw) != raw_length:
        raise ChipDBError("AGDB length mismatch")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChipDBError("invalid AGDB JSON payload") from exc
    if payload.get("schema") != schema or not isinstance(payload.get("datasets"), dict):
        raise ChipDBError("invalid AGDB envelope")
    result = {}
    for name, records in payload["datasets"].items():
        mapping = {}
        for record in records:
            if not isinstance(record, list) or len(record) != 2:
                raise ChipDBError("invalid AGDB mapping record")
            key, value = _decode(record[0]), _decode(record[1])
            if key in mapping:
                raise ChipDBError("duplicate AGDB key in %s" % name)
            mapping[key] = value
        result[name] = mapping
    if expected is not None and set(result) != set(expected):
        raise ChipDBError("AGDB datasets %r; expected %r" % (sorted(result), sorted(expected)))
    return result, payload.get("metadata", {})


def dump(path, datasets, *, metadata=None):
    with open(path, "wb") as stream:
        stream.write(dumps(datasets, metadata=metadata))


def load(path, *, expected=None):
    with open(path, "rb") as stream:
        return loads(stream.read(), expected=expected)
