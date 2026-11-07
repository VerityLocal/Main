"""Narrow browser-native bootstrap: pair the caller and start the local helper."""
import argparse
import hashlib
import http.client
import json
import os
import secrets
import struct
import subprocess
import sys
import time
from pathlib import Path

from .server import ORIGIN
from .local_os import binary_native_stdio, bootstrap_lock, helper_process_options, private_opener, reject_link

MAX_MESSAGE = 8192


def read_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError("Incomplete native message")
    size = struct.unpack("<I", header)[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError("Native message exceeds limit")
    body = stream.read(size)
    if len(body) != size:
        raise ValueError("Incomplete native message")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("Invalid native message")
    return value


def write_message(stream, value):
    body = json.dumps(value, allow_nan=False).encode()
    stream.write(struct.pack("<I", len(body)) + body)
    stream.flush()


def save_config(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    reject_link(path)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8))
    try:
        with open(temporary, "x", opener=private_opener) as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def initialize_config(path, origin):
    path = Path(path)
    reject_link(path)
    if path.exists():
        value = json.loads(path.read_text())
        if not isinstance(value.get("token"), str) or len(value["token"]) < 32:
            raise ValueError("Invalid existing pairing configuration")
    else:
        value = {"token": secrets.token_urlsafe(32), "origins": [], "signals": {}, "max_queries": 24, "idle_seconds": 1800}
    if origin not in value["origins"]:
        value["origins"].append(origin)
        save_config(path, value)
    return value


def request_helper(token, path="/health", data=None):
    connection = http.client.HTTPConnection("127.0.0.1", 8790, timeout=30 if path == "/extract" else 2)
    try:
        headers = {"Authorization": "Bearer " + token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        connection.request("GET" if data is None else "POST", path, body=None if data is None else json.dumps(data), headers=headers)
        response = connection.getresponse()
        body = response.read(8193)
        if len(body) > 8192 or response.status != 200:
            raise ValueError("port_conflict")
        return json.loads(body)
    finally:
        connection.close()


def validate_caller(message, caller_args, release):
    origin = message.get("origin", "")
    if message.get("type") != "bootstrap" or message.get("protocol") != 1 or not ORIGIN.fullmatch(origin):
        raise ValueError("Invalid bootstrap")
    if origin.startswith("chrome-extension://"):
        # Chromium supplies the initiating origin as argv; never trust JSON alone.
        if origin != release["chrome_origin"] or origin + "/" not in caller_args:
            raise ValueError("Unapproved extension")
    elif release["firefox_id"] not in caller_args:
        # Firefox supplies its allowed extension ID after the host-manifest path.
        raise ValueError("Unapproved extension")
    return origin


def bootstrap(message, caller_args, release, config_path, entrypoint):
    # Serialize simultaneous first opens so the pairing token is never replaced.
    validate_caller(message, caller_args, release)
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.with_name(path.name + ".lock")
    with bootstrap_lock(lock_path):
        return _bootstrap(message, caller_args, release, config_path, entrypoint)


def _bootstrap(message, caller_args, release, config_path, entrypoint):
    origin = validate_caller(message, caller_args, release)
    config = initialize_config(config_path, origin)
    installation_id = hashlib.sha256(str(Path(entrypoint).resolve().parent).encode()).hexdigest()[:24]
    if config.get("installation_id") != installation_id:
        config["installation_id"] = installation_id
        save_config(config_path, config)
    try:
        health = request_helper(config["token"])
        if health.get("installation_id") != installation_id:
            # Authenticated ownership check succeeded; replace only our older runtime.
            request_helper(config["token"], "/shutdown", {})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                time.sleep(0.15)
                request_helper(config["token"])
            raise ValueError("start_failed")
    except (ConnectionRefusedError, ConnectionResetError, TimeoutError, OSError):
        subprocess.Popen([sys.executable, "-I", str(entrypoint), "server", "--config", str(config_path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **helper_process_options())
        deadline = time.monotonic() + 15
        while True:
            try:
                health = request_helper(config["token"])
                break
            except (ConnectionRefusedError, ConnectionResetError, TimeoutError, OSError):
                if time.monotonic() >= deadline:
                    raise ValueError("start_failed")
                time.sleep(0.15)
    if not health.get("ready") or health.get("version") != release["engine_version"]:
        raise ValueError("incompatible_runtime")
    # Also pair in the running process (important for Firefox's per-install UUID).
    request_helper(config["token"], "/pair", {"origin": origin})
    return {"protocol": 1, "ready": True, "origin": origin, "token": config["token"]}


def main():
    binary_native_stdio()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--entrypoint", type=Path, required=True)
    args, caller = parser.parse_known_args()
    try:
        message = read_message(sys.stdin.buffer)
        if message is None:
            return
        release = json.loads(args.release.read_text())
        response = bootstrap(message, caller, release, args.config, args.entrypoint)
    except Exception as error:
        # No paths, token, upstream exceptions or document data on stdout/stderr.
        code = "port_conflict" if str(error) == "port_conflict" else "start_failed"
        response = {"protocol": 1, "ready": False, "code": code}
    write_message(sys.stdout.buffer, response)


if __name__ == "__main__":
    main()
