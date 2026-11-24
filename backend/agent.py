"""Wireless backup, the PC being backed up (B): a small READ-ONLY file server for paired PCs.

 - Off by default and never starts by itself. The owner turns it on, chooses the shared folders and shows a pairing code.
 - One TLS port. A PC pairs once with a one-time code (SPAKE2, so the code cannot be guessed offline or read from the
   network). After that it is recognised by its certificate; anything else is refused.
 - Only the shared folders can be read, never anything else, and never this app's own data (it holds the private key).
 - Only addresses on the local network are served.
Nothing here can write, delete or run anything on this PC."""
import collections, hashlib, hmac, ipaddress, json, os, re, secrets, socket, ssl, threading, time
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request
from werkzeug.serving import ThreadedWSGIServer

import pki
from spake2 import SPAKE2_B

BASE_PORT = 5200
DISCOVERY_PORT = 5199
PAIR_SECONDS = 300
PAIR_TRIES = 5
DENY_NAMES = {".ssh", ".gnupg", ".aws", ".azure", ".kube"}        # never served, wherever they are
ID_A, ID_B = b"ala-eh-client", b"ala-eh-agent"


def is_lan(addr):
    """True for this PC and for private or link-local network addresses. A public address is never served."""
    try:
        ip = ipaddress.ip_address(str(addr).split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def lan_addresses():
    out = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))                    # no packet is sent: this only picks the outgoing interface
            out.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in out and not ip.startswith("127."):
                out.append(ip)
    except OSError:
        pass
    return [ip for ip in out if is_lan(ip) and not ip.startswith("127.")] or out


def mac(key, role, server_fp, client_fp):
    """Key confirmation. It binds the shared key to both certificates, so a PC in the middle that shows its own
    certificate to each side cannot make the two confirmations agree."""
    return hmac.new(key, f"{role}|{server_fp}|{client_fp}".encode(), hashlib.sha256).hexdigest()


class _TlsServer(ThreadedWSGIServer):
    """Wraps every accepted connection with the CURRENT TLS context, so a new pairing or a revoke takes effect at once."""
    context_for = None

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(30)                                     # a stalled or silent client must not hold a thread forever
        return self.context_for().wrap_socket(sock, server_side=True, do_handshake_on_connect=False), addr

    def handle_error(self, request, client_address):            # failed handshakes from unknown devices are normal: stay quiet
        pass


class Agent:
    def __init__(self, folder_fn, name_fn, id_fn, compile_rules):
        self.folder_fn, self.name_fn, self.id_fn, self.compile_rules = folder_fn, name_fn, id_fn, compile_rules
        self.lock = threading.RLock()
        self.server = self.thread = self.timer = self.pair_timer = self.disc_sock = None
        self.port = None
        self.pairing = None
        self.connected = {}
        self.log = collections.deque(maxlen=200)
        self._ident = None
        self.app = self._build_app()

    # ------------------------------------------------------------ files and identity
    def folder(self):
        f = Path(self.folder_fn())
        f.mkdir(parents=True, exist_ok=True)
        return f

    def identity(self):
        f = str(self.folder())
        if not self._ident or self._ident[0] != f:
            self._ident = (f, pki.Identity(f))
        return self._ident[1]

    def _read(self, name, default):
        try:
            return json.loads((self.folder() / name).read_text("utf8"))
        except (OSError, ValueError):
            return default

    def _write(self, name, obj):
        p = self.folder() / name
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(obj, indent=1), "utf8")
        os.replace(tmp, p)

    def config(self):
        c = {"roots": [], "auto_off_hours": 8}
        c.update(self._read("agent.json", {}))
        return c

    def clients(self):
        return self._read("clients.json", [])

    # ------------------------------------------------------------ shared folders
    def set_roots(self, paths):
        """Choose the shared folders. Each gets a short unique label that the other PC sees instead of the real path."""
        data = self.folder().parent.resolve()
        roots, used = [], set()
        for p in paths:
            p = os.path.normpath(str(p).strip())
            if not p or p.startswith("\\\\") or p.startswith("//"):
                raise ValueError("Network paths cannot be shared. Use a folder on this PC.")
            if not os.path.isdir(p):
                raise ValueError(f"Not a folder: {p}")
            real = Path(os.path.realpath(p))
            if real == data or data in real.parents or real in data.parents:
                raise ValueError("This app's own data folder, or a folder that contains it, cannot be shared.")
            base = re.sub(r'[<>:"/\\|?*]', "_", Path(p).name or p.replace(":", "").strip("\\/") or "root").strip(" .") or "root"
            label, n = base, 2
            while label.lower() in used:
                label, n = f"{base}_{n}", n + 1
            used.add(label.lower())
            roots.append({"label": label, "path": p})
        c = self.config()
        c["roots"] = roots
        self._write("agent.json", c)
        return roots

    def set_auto_off(self, hours):
        c = self.config()
        c["auto_off_hours"] = max(0, min(168, int(hours)))
        self._write("agent.json", c)

    def resolve(self, label, rel):
        """The real path of `rel` inside the shared folder `label`, or None when it is not allowed."""
        root = next((r["path"] for r in self.config()["roots"] if r["label"] == label), None)
        if root is None:
            return None
        parts = [x for x in str(rel).replace("\\", "/").split("/") if x not in ("", ".")]
        if any(x == ".." or ":" in x or x.lower() in DENY_NAMES for x in parts):
            return None
        real_root = os.path.realpath(root)
        p = os.path.realpath(os.path.join(real_root, *parts))
        nr, np_ = os.path.normcase(real_root), os.path.normcase(p)
        if np_ != nr and not np_.startswith(nr.rstrip(os.sep) + os.sep):
            return None                                           # a link or a trick leading outside the shared folder
        data = os.path.normcase(str(self.folder().parent.resolve()))
        if np_ == data or np_.startswith(data + os.sep):
            return None                                           # never this app's own data (it holds the private key)
        return p

    # ------------------------------------------------------------ the TLS server
    def _context(self):
        return pki.server_context(self.identity(), "".join(c["cert"] for c in self.clients()))

    def start(self, host="0.0.0.0", port=None, discovery=True):
        with self.lock:
            if self.server:
                return self.status()
            self.identity()
            srv = None
            for p in ([port] if port is not None else range(BASE_PORT, BASE_PORT + 30)):
                try:
                    srv = _TlsServer(host, p, self.app)
                    break
                except OSError:
                    continue
            if srv is None:
                raise RuntimeError("No free port was found for sharing.")
            srv.context_for = self._context
            self.server, self.port = srv, srv.server_port
            self.thread = threading.Thread(target=srv.serve_forever, daemon=True)
            self.thread.start()
            hours = self.config()["auto_off_hours"]
            if hours:
                self.timer = threading.Timer(hours * 3600, self.stop)
                self.timer.daemon = True
                self.timer.start()
            if discovery:
                self._start_discovery()
            self._note("-", "sharing", "started", 200)
            return self.status()

    def stop(self):
        with self.lock:
            for t in (self.timer, self.pair_timer):
                if t:
                    t.cancel()
            self.timer = self.pair_timer = self.pairing = None
            if self.disc_sock:
                try:
                    self.disc_sock.close()
                except OSError:
                    pass
                self.disc_sock = None
            srv, self.server, self.port = self.server, None, None
            self.connected.clear()
        if srv:
            srv.shutdown()
            srv.server_close()
            self._note("-", "sharing", "stopped", 200)
        return self.status()

    # ------------------------------------------------------------ pairing
    def new_pairing(self):
        with self.lock:
            if not self.server:
                raise RuntimeError("Turn sharing on first.")
            if not self.config()["roots"]:
                raise RuntimeError("Choose at least one folder to share first.")
            if self.pair_timer:
                self.pair_timer.cancel()
            self.pairing = {"code": f"{secrets.randbelow(10 ** 6):06d}", "expires": time.time() + PAIR_SECONDS, "fails": 0, "sessions": {}}
            self.pair_timer = threading.Timer(PAIR_SECONDS, self.close_pairing)
            self.pair_timer.daemon = True
            self.pair_timer.start()
            return self._pairing_view()

    def close_pairing(self):
        with self.lock:
            self.pairing = None
            if self.pair_timer:
                self.pair_timer.cancel()
                self.pair_timer = None

    def _pairing_view(self):
        p = self.pairing
        return {"code": p["code"], "expires_in": max(0, int(p["expires"] - time.time()))} if p and p["expires"] > time.time() else None

    def revoke(self, cid):
        with self.lock:
            keep = [c for c in self.clients() if c["id"] != cid]
            self._write("clients.json", keep)
            self.connected.pop(cid, None)
        self._note("-", "revoked", cid[:12], 200)

    # ------------------------------------------------------------ discovery (so the other PC can find this one)
    def _start_discovery(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("", DISCOVERY_PORT))
        except OSError:
            return
        self.disc_sock = s

        def loop():
            while self.disc_sock is s:
                try:
                    data, addr = s.recvfrom(256)
                except OSError:
                    return
                reply = self.discovery_reply(data, addr[0])
                if reply:
                    try:
                        s.sendto(reply, addr)
                    except OSError:
                        pass
        threading.Thread(target=loop, daemon=True).start()

    def discovery_reply(self, data, addr):
        if data.strip() != b"ALAEH-DISCOVER" or not self.server or not is_lan(addr):
            return None
        return json.dumps({"app": "ala-eh", "id": self.id_fn(), "name": self.name_fn(), "port": self.port}).encode()

    # ------------------------------------------------------------ status and log
    def _note(self, who, what, path, status):
        entry = {"at": datetime.now().isoformat(sep=" ", timespec="seconds"), "who": who, "what": what, "path": str(path)[:200], "status": status}
        self.log.append(entry)
        try:
            f = self.folder() / "access.log"
            if f.exists() and f.stat().st_size > 1_000_000:
                f.replace(f.with_name("access.old.log"))
            with open(f, "a", encoding="utf8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def status(self):
        with self.lock:
            now = time.time()
            c = self.config()
            return {
                "running": bool(self.server), "port": self.port, "addresses": lan_addresses(), "name": self.name_fn(),
                "roots": c["roots"], "auto_off_hours": c["auto_off_hours"],
                "pairing": self._pairing_view() if self.pairing else None,
                "clients": [{"id": x["id"], "name": x["name"], "added": x.get("added", ""), "last_seen": x.get("last_seen", "")} for x in self.clients()],
                "connected": [{"id": k, "name": v["name"], "seconds_ago": int(now - v["at"]), "reading": v["path"]}
                              for k, v in self.connected.items() if now - v["at"] < 60],
                "log": list(self.log)[-30:][::-1], "fingerprint": self.identity().fp[:16],
            }

    # ------------------------------------------------------------ the HTTP API
    def _client(self):
        """The paired PC making this request (from its certificate), or None."""
        sock = request.environ.get("werkzeug.socket")
        try:
            der = sock.getpeercert(binary_form=True)
        except (AttributeError, ValueError, ssl.SSLError):
            der = None
        if not der:
            return None
        fp = pki.fingerprint(der)
        return next((c for c in self.clients() if c["id"] == fp), None)

    def _build_app(self):
        app = Flask("ala-eh-agent")
        app.config["MAX_CONTENT_LENGTH"] = 1 << 20
        agent = self

        @app.before_request
        def guard():
            if not is_lan(request.remote_addr):
                return jsonify(error="local network only"), 403
            if not agent.server:
                return jsonify(error="sharing is off"), 503
            if request.path.startswith("/v1/pair/"):
                return None
            c = agent._client()
            if not c:
                agent._note(request.remote_addr, request.method, request.path, 401)
                return jsonify(error="not paired"), 401
            with agent.lock:
                agent.connected[c["id"]] = {"name": c["name"], "at": time.time(), "path": request.args.get("path") or request.path}
            request.environ["ala.client"] = c

        @app.after_request
        def note(resp):
            c = request.environ.get("ala.client")
            if c and request.path not in ("/v1/hello",):
                agent._note(c["name"], request.method, f"{request.args.get('root', '')}/{request.args.get('path', '')}".strip("/") or request.path, resp.status_code)
            return resp

        @app.get("/v1/hello")
        def hello():
            return jsonify(app="ala-eh", v=1, id=agent.id_fn(), name=agent.name_fn(), roots=[r["label"] for r in agent.config()["roots"]])

        def where():
            p = agent.resolve(request.args.get("root", ""), request.args.get("path", ""))
            if p is None:
                return None, (jsonify(error="not a shared path"), 403)
            return p, None

        @app.get("/v1/list")
        def list_():
            p, err = where()
            if err:
                return err
            out = []
            try:
                with os.scandir(p) as it:
                    for e in it:
                        if e.name.lower() in DENY_NAMES:
                            continue
                        try:
                            st = e.stat()
                            out.append({"name": e.name, "dir": e.is_dir(follow_symlinks=False), "size": st.st_size, "mtime": st.st_mtime})
                        except OSError:
                            pass
            except OSError as e:
                return jsonify(error=str(e)), 404
            return jsonify(entries=out)

        @app.get("/v1/stat")
        def stat_():
            p, err = where()
            if err:
                return err
            try:
                st = os.stat(p)
            except OSError as e:
                return jsonify(error=str(e)), 404
            return jsonify(size=st.st_size, mtime=st.st_mtime)

        @app.get("/v1/hash")
        def hash_():
            p, err = where()
            if err:
                return err
            h = hashlib.sha256()
            try:
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
            except OSError as e:
                return jsonify(error=f"cannot be read: {e}"), 423
            return jsonify(sha256=h.hexdigest())

        @app.get("/v1/file")
        def file_():
            p, err = where()
            if err:
                return err
            try:
                fh = open(p, "rb")
                size = os.fstat(fh.fileno()).st_size
            except OSError as e:
                return jsonify(error=f"cannot be read: {e}"), 423      # for example a file another program keeps open

            def chunks():
                with fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        yield chunk
            return Response(chunks(), mimetype="application/octet-stream", headers={"Content-Length": str(size)})

        @app.post("/v1/walk")
        def walk():
            b = request.get_json(silent=True) or {}
            p = agent.resolve(str(b.get("root", "")), str(b.get("path", "")))
            if p is None:
                return jsonify(error="not a shared path"), 403
            match = agent.compile_rules([str(x) for x in (b.get("rules") or [])][:500])
            maxb = max(0, int(b.get("max_bytes") or 0))
            data = os.path.normcase(str(agent.folder().parent.resolve()))
            return Response(agent._walk(p, match, maxb, data), mimetype="application/x-ndjson")

        @app.post("/v1/pair/start")
        def pair_start():
            b = request.get_json(silent=True) or {}
            with agent.lock:
                pr = agent.pairing
                if not pr or pr["expires"] < time.time() or pr["fails"] >= PAIR_TRIES:
                    return jsonify(error="no pairing is open on that PC"), 403
                try:
                    sp = SPAKE2_B(pr["code"].encode(), idA=ID_A, idB=ID_B)
                    msg = sp.start()
                    key = sp.finish(bytes.fromhex(str(b.get("msg", ""))))
                except Exception:
                    pr["fails"] += 1
                    return jsonify(error="bad pairing message"), 400
                sid = secrets.token_hex(16)
                pr["sessions"][sid] = {"key": key, "name": str(b.get("name") or "PC")[:60]}
                if len(pr["sessions"]) > 10:
                    pr["sessions"].pop(next(iter(pr["sessions"])))
            return jsonify(session=sid, msg=msg.hex())

        @app.post("/v1/pair/finish")
        def pair_finish():
            b = request.get_json(silent=True) or {}
            with agent.lock:
                pr = agent.pairing
                if not pr or pr["expires"] < time.time() or pr["fails"] >= PAIR_TRIES:
                    return jsonify(error="no pairing is open on that PC"), 403
                s = pr["sessions"].pop(str(b.get("session", "")), None)
                try:
                    client_fp = pki.check_cert_pem(str(b.get("cert", "")))
                    ok = bool(s) and hmac.compare_digest(str(b.get("mac", "")), mac(s["key"], "client", agent.identity().fp, client_fp))
                except ValueError:
                    ok = False
                if not ok:
                    pr["fails"] += 1                                  # a wrong code: after PAIR_TRIES the code is dead
                    left = PAIR_TRIES - pr["fails"]
                    if left <= 0:
                        agent.close_pairing()
                    agent._note(request.remote_addr, "pairing", f"wrong code ({max(left, 0)} tries left)", 403)
                    return jsonify(error="the code did not match"), 403
                clients = [c for c in agent.clients() if c["id"] != client_fp]
                clients.append({"id": client_fp, "name": s["name"], "cert": str(b["cert"]), "added": datetime.now().isoformat(sep=" ", timespec="seconds"), "last_seen": ""})
                agent._write("clients.json", clients)
                reply = mac(s["key"], "server", agent.identity().fp, client_fp)
                agent.close_pairing()                                 # one code, one pairing
            agent._note(request.remote_addr, "pairing", f"paired with {s['name']}", 200)
            return jsonify(mac=reply, id=agent.id_fn(), name=agent.name_fn(), port=agent.port)

        return app

    def _walk(self, start, match, maxb, data):
        """Every file under `start` as one JSON line each, with the same skip rules a local scan uses."""
        sep = os.sep
        base = os.path.realpath(start)
        stack = [(base, "")]
        count = 0
        while stack:
            dp, reld = stack.pop()
            try:
                it = os.scandir(dp)
            except OSError:
                yield json.dumps({"err": reld}) + "\n"
                continue
            with it:
                for e in it:
                    name = e.name
                    rel = reld + "/" + name if reld else name
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if getattr(e, "is_junction", lambda: False)() or name.lower() in DENY_NAMES or match(name.lower(), rel.lower()):
                                continue
                            if os.path.normcase(os.path.realpath(e.path)) == data:
                                continue
                            stack.append((e.path, rel))
                            continue
                        if match(name.lower(), rel.lower()) or e.is_symlink():
                            continue
                        st = e.stat()
                    except OSError:
                        continue
                    if maxb and st.st_size > maxb:
                        continue
                    count += 1
                    yield json.dumps({"p": rel, "s": st.st_size, "m": st.st_mtime}) + "\n"
        yield json.dumps({"done": True, "count": count}) + "\n"
