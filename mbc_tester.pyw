#!/usr/bin/env python3
"""MBC 장면 전환 신호 보내기 창 — 더블클릭(.pyw 라 cmd 창이 안 뜸) 또는 pythonw mbc_tester.pyw

제안서 규칙대로 POST http://<IP>:<포트>/api/scenes/change 에 {"request_id","scene_id","sound_id"}(JSON)를 보내고
돌아온 응답 코드·내용을 아래 기록에 쌓는다. 서버는 받는 쪽(예: mbs_server.py)을 그대로 쓴다 — 이 프로그램은 보내기만 한다.
파이썬 3 표준 라이브러리만 쓴다(tkinter).
"""
import json
import secrets
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import ttk

PATH = "/api/scenes/change"


_SEQ = [0]


def new_id():
    """test-001-<난수 6자>, test-002-<난수 6자> … — 차례 번호 + 뒤에 난수(기록 지우기로 001 부터 다시 써도 서버가 기억하는 예전 ID 와 안 겹친다)."""
    _SEQ[0] += 1
    return "test-%03d-%s" % (_SEQ[0], secrets.token_hex(3))


def post(url, body, timeout):
    """(코드|None, 응답 글 또는 오류 글, ms)."""
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace"), round((time.monotonic() - t0) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), round((time.monotonic() - t0) * 1000)
    except Exception as e:  # noqa: BLE001 — 연결 거부·시간 초과
        why = getattr(e, "reason", e)
        ms = round((time.monotonic() - t0) * 1000)
        if "timed out" in str(why).lower() or isinstance(why, TimeoutError):
            return None, "%g초 안에 응답 없음" % timeout, ms
        return None, "보내지 못함: %s" % why, ms


class App:
    def __init__(self, root):
        self.root = root
        self.last = None                      # (url, body)
        root.title("MBC 신호 보내기")
        root.minsize(760, 480)
        f = ttk.Frame(root, padding=10)
        f.pack(fill="both", expand=True)

        self.ip = tk.StringVar(value="127.0.0.1")
        self.port = tk.StringVar(value="8081")
        self.path = tk.StringVar(value=PATH)
        self.timeout = tk.StringVar(value="30")
        self.rid = tk.StringVar(value=new_id())
        self.scene = tk.StringVar(value="scene_01")
        self.sound = tk.StringVar(value="sound_01")
        self.autoid = tk.BooleanVar(value=True)

        top = ttk.Frame(f)
        top.pack(fill="x")
        for i, (lab, var, w) in enumerate((("서버 IP", self.ip, 16), ("포트", self.port, 7), ("경로", self.path, 24),
                                           ("대기(초)", self.timeout, 5))):
            ttk.Label(top, text=lab).grid(row=0, column=i * 2, sticky="w", padx=(0 if i == 0 else 10, 4))
            ttk.Entry(top, textvariable=var, width=w).grid(row=0, column=i * 2 + 1, sticky="w")
        ids = ttk.Frame(f)
        ids.pack(fill="x", pady=(8, 0))
        for i, (lab, var, w) in enumerate((("request_id", self.rid, 22), ("scene_id", self.scene, 16), ("sound_id", self.sound, 16))):
            ttk.Label(ids, text=lab).grid(row=0, column=i * 2, sticky="w", padx=(0 if i == 0 else 10, 4))
            ttk.Entry(ids, textvariable=var, width=w).grid(row=0, column=i * 2 + 1, sticky="w")
        opt = ttk.Frame(f)
        opt.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(opt, text="보낼 때마다 새 request_id", variable=self.autoid).pack(side="left")
        ttk.Button(opt, text="새 ID", command=lambda: self.rid.set(new_id())).pack(side="left", padx=6)
        ttk.Label(opt, text="(scene_id·sound_id 는 비우면 요청에서 뺌)").pack(side="left", padx=6)

        btn = ttk.Frame(f)
        btn.pack(fill="x", pady=(8, 6))
        ttk.Button(btn, text="보내기", command=self.send_normal).pack(side="left")
        ttk.Button(btn, text="마지막 요청 다시 보내기", command=self.resend).pack(side="left", padx=6)
        ttk.Button(btn, text="409 시험", command=self.t409).pack(side="right")
        ttk.Button(btn, text="404 시험", command=self.t404).pack(side="right", padx=6)
        ttk.Button(btn, text="400 시험", command=self.t400).pack(side="right")
        ttk.Button(btn, text="기록 지우기", command=self.clear).pack(side="right", padx=12)

        cols = ("time", "url", "body", "status", "resp", "ms")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=14)
        for c, t, w in (("time", "시각", 90), ("url", "보낸 곳", 230), ("body", "보낸 본문", 260), ("status", "응답 코드", 70),
                        ("resp", "응답 내용", 260), ("ms", "걸린 시간", 70)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w", stretch=(c in ("url", "body", "resp")))
        self.tree.tag_configure("ok", foreground="#15803d")
        self.tree.tag_configure("warn", foreground="#b45309")
        self.tree.tag_configure("err", foreground="#b91c1c")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # -- 요청 만들기 --
    def url(self, path=None):
        p = path or self.path.get().strip() or "/"
        if not p.startswith("/"):
            p = "/" + p
        return "http://%s:%s%s" % (self.ip.get().strip(), self.port.get().strip(), p)

    def body(self, rid=None, scene=None, with_rid=True):
        d = {}
        if with_rid:
            d["request_id"] = self.rid.get() if rid is None else rid
        s = (self.scene.get() if scene is None else scene).strip()
        n = self.sound.get().strip()
        if s:
            d["scene_id"] = s                 # 선택하지 않은 ID 는 요청에서 뺀다(제안서)
        if n:
            d["sound_id"] = n
        return json.dumps(d, ensure_ascii=False)

    def tmo(self):
        try:
            return max(1.0, float(self.timeout.get()))
        except ValueError:
            return 30.0

    # -- 보내기(딸림 스레드 — 창은 안 멈춘다) --
    def send(self, url, body):
        self.last = (url, body)
        tmo = self.tmo()

        def work():
            code, text, ms = post(url, body, tmo)
            self.root.after(0, self.add, url, body, code, text, ms)
        threading.Thread(target=work, daemon=True).start()

    def add(self, url, body, code, text, ms):
        tag = "err" if code is None or code >= 500 else ("ok" if 200 <= code < 300 else "warn")
        t = time.strftime("%H:%M:%S") + ".%03d" % (int(time.time() * 1000) % 1000)
        self.tree.insert("", 0, values=(t, url, body, "-" if code is None else code, text, "%d ms" % ms), tags=(tag,))

    def clear(self):
        """기록을 지우고 request_id 를 test-001 부터 다시."""
        self.tree.delete(*self.tree.get_children())
        _SEQ[0] = 0
        self.rid.set(new_id())
        self.last = None

    def send_normal(self):
        self.send(self.url(), self.body())     # 칸에 보이는 ID 로 보내고
        if self.autoid.get():
            self.rid.set(new_id())             # 다음 ID 를 미리 보여 준다(test-001 → test-002)

    def resend(self):
        if self.last:
            self.send(*self.last)

    def t400(self):                           # request_id 없음 → 400
        self.send(self.url(), self.body(with_rid=False))

    def t404(self):                           # 틀린 경로 → 404
        self.send(self.url("/api/scenes/wrong-path"), self.body())

    def t409(self):                           # 같은 request_id, 다른 내용 → 409
        if not self.last:
            self.send_normal()
            return
        try:
            d = json.loads(self.last[1])
        except ValueError:
            d = {}
        rid = d.get("request_id") or self.rid.get()
        self.send(self.url(), self.body(rid=rid, scene=(d.get("scene_id") or "scene") + "_other"))


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
