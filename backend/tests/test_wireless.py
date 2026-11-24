"""Wireless backup: two PCs talking over real TLS on this machine (B shares folders, A pairs and reads them)."""
import http.client
import json
import os
import time
from pathlib import Path

import pytest

import agent as agent_mod
import app as backup
import pki
import remote


class Pair:
    """B: the PC that shares. A: the PC that backs it up. Each has its own state folder, like two real PCs."""

    def __init__(self, root: Path):
        self.root = root
        self.docs = root / "b" / "docs"
        self.docs.mkdir(parents=True)
        self.b = agent_mod.Agent(lambda: root / "b" / "data" / "agent", lambda: "OFFICE-PC", lambda: "b-id-1234567890", backup.compile_rules)
        self.ident_a = pki.Identity(root / "a" / "data" / "agent")
        self.b.set_roots([str(self.docs)])
        self.st = self.b.start(host="127.0.0.1", port=0, discovery=False)
        self.port = self.st["port"]

    def write(self, rel, text="x"):
        p = self.docs / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def pair(self, name="LAPTOP", ident=None):
        code = self.b.new_pairing()["code"]
        return remote.pair("127.0.0.1", self.port, code, name, ident or self.ident_a)

    def client(self, peer=None, ident=None):
        return remote.RemoteClient(peer or self.pair(), ident or self.ident_a)


@pytest.fixture
def pr(tmp_path):
    p = Pair(tmp_path)
    yield p
    p.b.stop()


# ---------------------------------------------------------------- pairing and access

def test_pair_then_browse_and_read(pr):
    pr.write("Reports/a.txt", "hello world")
    peer = pr.pair()
    assert peer["name"] == "OFFICE-PC" and peer["id"] == "b-id-1234567890" and peer["port"] == pr.port
    c = remote.RemoteClient(peer, pr.ident_a)
    assert c.hello()["roots"] == ["docs"]
    assert [e["name"] for e in c.list("docs", "Reports")] == ["a.txt"]
    assert c.stat("docs", "Reports/a.txt")[0] == 11
    import hashlib
    assert c.hash("docs", "Reports/a.txt") == hashlib.sha256(b"hello world").hexdigest()
    with c.open("docs", "Reports/a.txt") as f:
        assert f.read(1 << 20) == b"hello world"
    assert pr.b.status()["clients"][0]["name"] == "LAPTOP"


def test_wrong_code_is_refused_and_five_wrong_tries_kill_the_code(pr):
    code = pr.b.new_pairing()["code"]
    wrong = f"{(int(code) + 1) % 10 ** 6:06d}"
    for _ in range(agent_mod.PAIR_TRIES):
        with pytest.raises(remote.RemoteError):
            remote.pair("127.0.0.1", pr.port, wrong, "EVIL", pr.ident_a)
    with pytest.raises(remote.RemoteError, match="no pairing"):                # even the right code no longer works
        remote.pair("127.0.0.1", pr.port, code, "LAPTOP", pr.ident_a)
    assert pr.b.status()["clients"] == []


def test_the_code_works_once_and_expires(pr):
    peer = pr.pair()
    assert peer
    assert pr.b.status()["pairing"] is None                                    # one code, one pairing
    code = pr.b.new_pairing()["code"]
    pr.b.pairing["expires"] = time.time() - 1
    with pytest.raises(remote.RemoteError, match="no pairing"):
        remote.pair("127.0.0.1", pr.port, code, "LAPTOP", pr.ident_a)


def test_an_unpaired_pc_gets_nothing(pr, tmp_path):
    pr.write("secret.txt", "s")
    peer = pr.pair()
    stranger = pki.Identity(tmp_path / "c" / "data" / "agent")
    with pytest.raises(remote.RemoteError):                                    # shows an unknown certificate: refused at the handshake
        remote.RemoteClient(peer, stranger).hello()
    ctx = pki.client_context(None)                                             # shows no certificate: refused by the agent
    conn = http.client.HTTPSConnection("127.0.0.1", pr.port, context=ctx, timeout=10)
    conn.request("GET", "/v1/file?root=docs&path=secret.txt")
    assert conn.getresponse().status == 401


def test_revoking_a_pc_cuts_it_off_at_once(pr):
    peer = pr.pair()
    c = remote.RemoteClient(peer, pr.ident_a)
    assert c.hello()
    pr.b.revoke(pr.b.status()["clients"][0]["id"])
    with pytest.raises(remote.RemoteError):
        c.hello()


def test_a_different_server_identity_is_refused_before_anything_is_sent(pr):
    peer = pr.pair()
    with pytest.raises(remote.RemoteError, match="not the one you paired with"):
        remote.RemoteClient({**peer, "fp": "0" * 64}, pr.ident_a).hello()


def test_sharing_off_means_unreachable(pr):
    peer = pr.pair()
    pr.b.stop()
    with pytest.raises(remote.RemoteError):
        remote.RemoteClient(peer, pr.ident_a).hello()


def test_only_the_local_network_is_served(pr):
    assert agent_mod.is_lan("192.168.1.5") and agent_mod.is_lan("10.0.0.2") and agent_mod.is_lan("127.0.0.1")
    assert agent_mod.is_lan("::ffff:10.0.0.1") and agent_mod.is_lan("169.254.3.4")
    assert not agent_mod.is_lan("8.8.8.8") and not agent_mod.is_lan("2606:4700::1") and not agent_mod.is_lan("nonsense")
    r = pr.b.app.test_client().get("/v1/hello", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert r.status_code == 403


# ---------------------------------------------------------------- the sandbox

def test_nothing_outside_the_shared_folder_can_be_read(pr, tmp_path):
    pr.write("ok.txt", "ok")
    (tmp_path / "b" / "outside.txt").write_text("private")
    b = pr.b
    assert b.resolve("docs", "ok.txt")
    for bad in ("../outside.txt", "..\\outside.txt", "a/../../outside.txt", "C:\\Windows\\win.ini", "ok.txt:stream", ".ssh/id_rsa", "x/.SSH/key"):
        assert b.resolve("docs", bad) is None, bad
    assert b.resolve("nope", "ok.txt") is None
    c = pr.client()
    for bad in ("../outside.txt", ".ssh/id_rsa"):
        with pytest.raises(remote.RemoteError, match="not a shared path"):
            c.stat("docs", bad)


def test_a_link_cannot_lead_out_of_the_shared_folder(pr, tmp_path):
    (tmp_path / "b" / "outside").mkdir()
    (tmp_path / "b" / "outside" / "x.txt").write_text("private")
    try:
        os.symlink(tmp_path / "b" / "outside", pr.docs / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symbolic links")
    assert pr.b.resolve("docs", "link/x.txt") is None


def test_the_apps_own_data_with_the_private_key_is_never_served(pr):
    data = pr.root / "b" / "data"
    with pytest.raises(ValueError, match="own data folder"):
        pr.b.set_roots([str(data)])
    with pytest.raises(ValueError, match="own data folder"):
        pr.b.set_roots([str(pr.root / "b")])                                   # a folder that contains it
    with pytest.raises(ValueError):
        pr.b.set_roots(["\\\\server\\share"])
    assert pr.b.resolve("docs", "../data/agent/identity.key.pem") is None


def test_walk_applies_the_skip_rules_and_never_lists_secrets(pr):
    pr.write("Docs/a.docx")
    pr.write("node_modules/lib/x.js")
    pr.write("Docs/cache.tmp")
    pr.write(".ssh/id_rsa", "KEY")
    pr.write("big.bin", "x" * 5000)
    c = pr.client()
    files = {i[0]: i for i in c.walk("docs", backup.rules(), 0) if i[0] != "!"}
    assert set(files) == {"Docs/a.docx", "big.bin"}
    assert set(i[0] for i in c.walk("docs", [], 1000) if i[0] != "!") == {"Docs/a.docx", ".ssh/id_rsa"} - {".ssh/id_rsa"} | {"Docs/cache.tmp"} | {"node_modules/lib/x.js"}


def test_discovery_answers_only_the_local_network_and_only_when_sharing(pr):
    ask = b"ALAEH-DISCOVER"
    d = json.loads(pr.b.discovery_reply(ask, "192.168.1.9"))
    assert d == {"app": "ala-eh", "id": "b-id-1234567890", "name": "OFFICE-PC", "port": pr.port}
    assert pr.b.discovery_reply(ask, "8.8.8.8") is None
    assert pr.b.discovery_reply(b"hello", "192.168.1.9") is None
    pr.b.stop()
    assert pr.b.discovery_reply(ask, "192.168.1.9") is None


def test_every_request_is_logged(pr):
    pr.write("a.txt")
    c = pr.client()
    c.stat("docs", "a.txt")
    log = pr.b.status()["log"]
    assert any(e["what"] == "GET" and "a.txt" in e["path"] and e["who"] == "LAPTOP" for e in log)
    assert any(e["what"] == "pairing" and "paired with LAPTOP" in e["path"] for e in log)
    assert (pr.root / "b" / "data" / "agent" / "access.log").exists()


# ---------------------------------------------------------------- backing up another PC through the normal app

@pytest.fixture
def wired(rig, pr, monkeypatch):
    """PC A is the app under test (its state is the rig's); PC B is `pr`. A is paired and told to back up B's `docs`."""
    peer = remote.pair("127.0.0.1", pr.port, pr.b.new_pairing()["code"], "A", backup.AGENT.identity())
    backup.PEERS.add(peer)
    monkeypatch.setitem(backup.SETTINGS, "sources", [])
    monkeypatch.setitem(backup.SETTINGS, "remote_sources", [{"pc": peer["id"], "root": "docs"}])
    return pr


def test_another_pc_is_scanned_backed_up_and_restorable(rig, wired, tmp_path):
    wired.write("Reports/q1.txt", "quarterly")
    wired.write("notes.txt", "notes")
    backup.scan_job()
    assert sorted(f["rel"] for f in backup.INDEX.values()) == ["Reports" + os.sep + "q1.txt", "notes.txt"]
    f = next(iter(backup.INDEX.values()))
    assert f["path"].startswith(os.sep * 2 + "OFFICE-PC" + os.sep + "docs") and f["remote"]["pc"] == "b-id-1234567890"
    rig.choose_all()
    backup.backup_job()
    base = rig.dest / backup.pc_folder(str(rig.dest)) / "Remote PCs" / "OFFICE-PC" / "docs"
    assert (base / "Reports" / "q1.txt").read_text() == "quarterly" and (base / "notes.txt").read_text() == "notes"
    assert all(backup.status(f, [str(rig.dest)]) == "backed_up" for f in backup.INDEX.values())
    assert "Everything is already backed up" in backup.backup_job()

    p = wired.docs / "notes.txt"                                               # B edits a file: the next backup picks it up
    p.write_text("notes, edited")
    os.utime(p, (time.time() + 10, time.time() + 10))
    backup.scan_job()
    backup.backup_job()
    assert (base / "notes.txt").read_text() == "notes, edited"

    ids = [i for i, f in backup.INDEX.items() if f["rel"] == "notes.txt"]       # restore needs somewhere to put it
    assert "1 failed" in backup.restore_job([{"id": ids[0], "dest": str(rig.dest)}], "", False)
    out = tmp_path / "restored"
    assert "Restored 1 files" in backup.restore_job([{"id": ids[0], "dest": str(rig.dest)}], str(out), False)
    assert (out / "Remote PCs" / "OFFICE-PC" / "docs" / "notes.txt").read_text() == "notes, edited"


def test_an_unreachable_pc_keeps_its_old_list_and_backups(rig, wired):
    wired.write("a.txt", "a")
    backup.scan_job()
    rig.choose_all()
    backup.backup_job()
    before = dict(backup.INDEX)
    wired.b.stop()                                                             # B goes to sleep
    backup.scan_job()
    assert backup.INDEX.keys() == before.keys()
    assert all(backup.status(f, [str(rig.dest)]) == "backed_up" for f in backup.INDEX.values())
    assert any("Could not scan OFFICE-PC" in r["message"] for r in backup.read_logs("warn", ""))


def test_a_file_changing_on_the_other_pc_during_backup_is_refused(rig, wired, monkeypatch):
    wired.write("a.txt", "one")
    backup.scan_job()
    f = next(iter(backup.INDEX.values()))
    wired.write("a.txt", "two two")                                            # edited after the scan measured it
    part = rig.root / "x.part"
    with pytest.raises(RuntimeError, match="changed while"):
        backup.copy_hashed(f, part, False)


def test_forgetting_a_pc_stops_backing_it_up(rig, wired):
    pid = "b-id-1234567890"
    assert rig.post(f"/api/peers/{pid}/forget").status_code == 200
    assert backup.SETTINGS["remote_sources"] == [] and backup.PEERS.get(pid) is None


# ---------------------------------------------------------------- the app's API

def test_api_share_and_pair_flow(rig, tmp_path, monkeypatch):
    docs = tmp_path / "share"
    docs.mkdir()
    (docs / "f.txt").write_text("hi")
    assert rig.post("/api/agent/pairing").status_code == 400                    # sharing must be on first
    assert rig.post("/api/agent/roots", {"roots": [str(docs)]}).json["roots"][0]["label"] == "share"
    monkeypatch.setattr(agent_mod, "BASE_PORT", 5200)
    st = backup.AGENT.start(host="127.0.0.1", port=0, discovery=False)
    try:
        assert rig.get("/api/stats").json["sharing"] is True
        code = rig.post("/api/agent/pairing").json["pairing"]["code"]
        assert len(code) == 6
        assert rig.post("/api/peers/pair", {"host": "8.8.8.8", "port": 5200, "code": code}).status_code == 400   # not a local address
        assert rig.get("/api/agent").json["port"] == st["port"]
    finally:
        backup.AGENT.stop()
    assert rig.get("/api/stats").json["sharing"] is False


def test_remote_sources_survive_a_settings_save(rig, monkeypatch):
    monkeypatch.setitem(backup.SETTINGS, "remote_sources", [{"pc": "x", "root": "docs"}])
    body = {k: v for k, v in rig.get("/api/settings").json.items() if k != "remote_sources"}
    assert rig.post("/api/settings", body).status_code == 200
    assert backup.SETTINGS["remote_sources"] == [{"pc": "x", "root": "docs"}]


def test_unsafe_file_names_from_another_pc_are_refused(rig, wired, monkeypatch):
    """A paired PC that misbehaves must not be able to make this PC write outside its backup folder."""
    good = [("ok.txt", 2, 1700000000.0)]
    evil = [("../../escape.txt", 1, 1.0), ("a/../../b.txt", 1, 1.0), ("C:/Windows/x.txt", 1, 1.0), ("/abs.txt", 1, 1.0), ("a\b.txt", 1, 1.0),
            ("con.txt", 1, 1.0), ("dir /x.txt", 1, 1.0), ("a//b.txt", 1, 1.0), ("x.txt:stream", 1, 1.0), ("neg.txt", -5, 1.0), ("bad.txt", "NaN", 1.0)]
    monkeypatch.setattr(remote.RemoteClient, "walk", lambda self, root, rules, maxb=0: iter(good + evil))
    backup.scan_job()
    assert sorted(f["rel"] for f in backup.INDEX.values()) == ["ok.txt"]
    assert any("refused as unsafe" in r["message"] for r in backup.read_logs("warn", ""))
    assert backup.clean_remote_rel("Reports/q1 (final).txt") == "Reports/q1 (final).txt"
