"""Wireless backup, the controller PC (A): pairs with another PC and reads its shared folders.

Every connection shows this PC's certificate (so the other PC knows who is asking) and checks that the other PC's
certificate is the one remembered at pairing, BEFORE anything is sent. A different certificate is refused."""
import hmac, http.client, json, re, socket, threading, time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import pki
from spake2 import SPAKE2_A

import agent as agent_mod

ID_A, ID_B = agent_mod.ID_A, agent_mod.ID_B


class RemoteError(Exception):
    """kind says why: 'refused' (the PC answers but sharing is off), 'unreachable' (no answer at all), 'rejected' (it no longer
    accepts this PC), 'identity' (not the PC that was paired) or 'other'."""

    def __init__(self, message, kind="other"):
        super().__init__(message)
        self.kind = kind


class PeerStore:
    """The PCs this PC is paired with (the ones it can back up): name, address, and the certificate fingerprint to expect."""

    def __init__(self, path_fn):
        self.path_fn = path_fn
        self.lock = threading.RLock()                   # several PCs are asked at once: their updates must not trample each other

    def all(self):
        try:
            return json.loads(Path(self.path_fn()).read_text("utf8"))
        except (OSError, ValueError):
            return []

    def get(self, pid):
        return next((p for p in self.all() if p["id"] == pid), None)

    def _save(self, peers):
        p = Path(self.path_fn())
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(peers, indent=1), "utf8")
        tmp.replace(p)

    def add(self, peer):
        with self.lock:
            peers = [p for p in self.all() if p["id"] != peer["id"]]
            peers.append(peer)
            self._save(peers)

    def update(self, pid, **kw):
        with self.lock:
            peers = self.all()
            for p in peers:
                if p["id"] == pid:
                    p.update(kw)
            self._save(peers)

    def remove(self, pid):
        with self.lock:
            self._save([p for p in self.all() if p["id"] != pid])


def _connect(host, port, identity, expect_fp=None, timeout=15):
    """An open TLS connection. When `expect_fp` is given the other PC must show exactly that certificate."""
    conn = http.client.HTTPSConnection(host, port, context=pki.client_context(identity), timeout=timeout)
    try:
        conn.connect()
        fp = pki.fingerprint(conn.sock.getpeercert(binary_form=True))
    except (OSError, ValueError) as e:
        conn.close()
        raise RemoteError(f"Cannot reach {host}:{port} ({e.__class__.__name__}: {e}). Is sharing on, and are both PCs on the same network?",
                          "refused" if isinstance(e, ConnectionRefusedError) else "unreachable") from e
    if expect_fp and fp != expect_fp:
        conn.close()
        raise RemoteError("That PC's identity is not the one you paired with. It was reinstalled or something is pretending to be it, so nothing was sent.", "identity")
    conn.fp = fp
    return conn


def _json(resp):
    body = resp.read()
    try:
        data = json.loads(body.decode("utf8") or "{}")
    except ValueError:
        data = {}
    if resp.status != 200:
        raise RemoteError(data.get("error") or f"the other PC answered {resp.status}", "rejected" if resp.status == 401 else "other")
    return data


def pair(host, port, code, my_name, identity):
    """Pair with the PC at host:port using the code it shows. Returns the peer record to remember."""
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != 6:
        raise RemoteError("The pairing code is 6 digits.")
    conn = _connect(host, port, None)
    server_fp = conn.fp
    conn.close()
    sp = SPAKE2_A(code.encode(), idA=ID_A, idB=ID_B)
    out = sp.start()
    conn = _connect(host, port, None, expect_fp=server_fp)
    try:
        conn.request("POST", "/v1/pair/start", json.dumps({"msg": out.hex(), "name": my_name}), {"Content-Type": "application/json"})
        start = _json(conn.getresponse())
    finally:
        conn.close()
    key = sp.finish(bytes.fromhex(start["msg"]))
    conn = _connect(host, port, None, expect_fp=server_fp)
    try:
        conn.request("POST", "/v1/pair/finish", json.dumps(
            {"session": start["session"], "mac": agent_mod.mac(key, "client", server_fp, identity.fp), "cert": identity.cert_pem, "name": my_name}),
            {"Content-Type": "application/json"})
        done = _json(conn.getresponse())
    finally:
        conn.close()
    if not hmac.compare_digest(done.get("mac", ""), agent_mod.mac(key, "server", server_fp, identity.fp)):
        raise RemoteError("The other PC could not prove it knew the code. Pairing was cancelled.")
    pid, pname = done.get("id"), done.get("name")
    if not (isinstance(pid, str) and re.fullmatch(r"[A-Za-z0-9_-]{4,64}", pid) and isinstance(pname, str) and 0 < len(pname) <= 60
            and isinstance(done.get("port"), int) and 0 < done["port"] < 65536):
        raise RemoteError("The other PC sent details this app does not accept, so pairing was cancelled.")
    return {"id": pid, "name": pname, "host": host, "port": done["port"], "fp": server_fp,
            "added": datetime.now().isoformat(sep=" ", timespec="seconds"), "last_seen": ""}


def discover(timeout=2.0):
    """PCs on this network that have sharing turned on: [{id, name, host, port}]."""
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.3)
    try:
        s.sendto(b"ALAEH-DISCOVER", ("255.255.255.255", agent_mod.DISCOVERY_PORT))
    except OSError:
        pass
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, addr = s.recvfrom(512)
        except socket.timeout:
            continue
        except OSError:
            break
        try:
            d = json.loads(data.decode("utf8"))
            if d.get("app") == "ala-eh" and agent_mod.is_lan(addr[0]):
                found[d["id"]] = {"id": d["id"], "name": str(d["name"])[:60], "host": addr[0], "port": int(d["port"])}
        except (ValueError, KeyError, TypeError):
            continue
    s.close()
    return list(found.values())


class RemoteFile:
    """A file being read from the other PC. Close it (or use `with`) to release the connection."""

    def __init__(self, conn, resp):
        self.conn, self.resp = conn, resp

    def read(self, n=-1):
        try:
            return self.resp.read(n if n and n > 0 else None)
        except (OSError, http.client.HTTPException) as e:
            raise RemoteError(f"The connection to the other PC dropped while reading ({e.__class__.__name__}).", "unreachable") from e

    def close(self):
        try:
            self.resp.close()
        finally:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class RemoteClient:
    def __init__(self, peer, identity, store=None, timeout=15):
        self.peer, self.identity, self.store, self.timeout = peer, identity, store, timeout

    def _open(self, method, path, params=None, body=None):
        url = path + ("?" + urlencode(params) if params else "")
        last = None
        for attempt in range(2):                      # the second try follows a change of the other PC's address
            try:
                conn = _connect(self.peer["host"], self.peer["port"], self.identity, expect_fp=self.peer["fp"], timeout=self.timeout)
                break
            except RemoteError as e:
                last = e
                if e.kind in ("identity", "refused") or attempt or not self._find_new_address():
                    raise
        else:
            raise last
        try:
            conn.request(method, url, json.dumps(body) if body is not None else None, {"Content-Type": "application/json"})
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise RemoteError(f"The other PC refused or dropped the connection ({e.__class__.__name__}). Its pairing with this PC may have been removed.", "rejected") from e
        if self.store:
            self.store.update(self.peer["id"], last_seen=datetime.now().isoformat(sep=" ", timespec="seconds"))
        return conn, resp

    def _find_new_address(self):
        """The other PC may have a new address on the network (DHCP): look for it by its id."""
        for f in discover(1.5):
            if f["id"] == self.peer["id"] and (f["host"], f["port"]) != (self.peer["host"], self.peer["port"]):
                self.peer = {**self.peer, "host": f["host"], "port": f["port"]}
                if self.store:
                    self.store.update(self.peer["id"], host=f["host"], port=f["port"])
                return True
        return False

    def call(self, path, params=None):
        conn, resp = self._open("GET", path, params)
        try:
            return _json(resp)
        finally:
            conn.close()

    def hello(self):
        return self.call("/v1/hello")

    def list(self, root, rel=""):
        return self.call("/v1/list", {"root": root, "path": rel})["entries"]

    def stat(self, root, rel):
        d = self.call("/v1/stat", {"root": root, "path": rel})
        return d["size"], d["mtime"]

    def hash(self, root, rel):
        return self.call("/v1/hash", {"root": root, "path": rel})["sha256"]

    def open(self, root, rel):
        conn, resp = self._open("GET", "/v1/file", {"root": root, "path": rel})
        if resp.status != 200:
            try:
                _json(resp)
            finally:
                conn.close()
        return RemoteFile(conn, resp)

    def walk(self, root, rules, max_bytes=0):
        """Yield (relative path, size, mtime) for every file, and ('!', folder) for a folder that could not be listed.
        Raises RemoteError if the listing stops before it is complete."""
        conn, resp = self._open("POST", "/v1/walk", body={"root": root, "path": "", "rules": list(rules), "max_bytes": max_bytes})
        try:
            if resp.status != 200:
                _json(resp)
            done = False
            for raw in resp:
                if not raw.strip():
                    continue
                d = json.loads(raw.decode("utf8"))
                if d.get("done"):
                    done = True
                elif "err" in d:
                    yield ("!", d["err"])
                else:
                    yield (d["p"], d["s"], d["m"])
            if not done:
                raise RemoteError("The list from the other PC was cut short.", "unreachable")
        except (OSError, http.client.HTTPException, ValueError) as e:
            raise RemoteError(f"The connection to the other PC dropped during the scan ({e.__class__.__name__}).", "unreachable") from e
        finally:
            conn.close()
