"""Browse Mods: the community mod list (d5lib.modindex) -- what's on offer, with pictures, installed in one click.

Every download is checked against the list (size, SHA-256) and as a package (only the file types mods use, no
program files, size limits) before the normal import (d5lib.modshare) puts it here.  "Post my mod…" puts a mod on
the list from here (d5lib.modpost: sign in with GitHub once, the kit does the rest); the list's maintainers review
the posts in "Review posts" and publish or decline them."""
import json
import os
import tempfile
import webbrowser

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressDialog,
                             QPushButton, QSplitter, QVBoxLayout, QWidget)

from d5lib import modindex, modpost, modshare
from d5lib.version import VERSION
from ..common import Banner, PageHeader, SearchBox, Worker, error_box

ROLE = Qt.ItemDataRole.UserRole
STATE_TEXT = {"new": "", "installed": "✔ installed", "update": "⬆ update", "newer": "✔ installed (newer)"}


class BrowsePage(QWidget):
    def __init__(self, ws, main):
        super().__init__()
        self.ws = ws
        self.index = None
        self.entry = None
        self._loading = False
        self.cache = os.path.join(os.path.dirname(ws.mods.mods_dir), "cache", "modindex")
        lay = QVBoxLayout(self)
        lay.addWidget(PageHeader("Browse Mods", "Mods other players share: pictures, what they add, installed in "
                                                "one click. Every download is checked before it is imported, and "
                                                "mods are reviewed before they are listed."))
        self.banner = Banner("")
        lay.addWidget(self.banner)
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.search = SearchBox("Search mods (name, author, tag)…")
        self.search.textChanged.connect(self._fill)
        ll.addWidget(self.search)
        row = QHBoxLayout()
        self.category = QComboBox()
        self.category.addItem("All kinds", None)
        for c in modindex.CATEGORIES:
            self.category.addItem(c, c)
        self.category.currentIndexChanged.connect(self._fill)
        row.addWidget(self.category)
        self.show_box = QComboBox()
        for k, t in (("all", "All mods"), ("new", "Not installed"), ("update", "Updates"), ("installed", "Installed")):
            self.show_box.addItem(t, k)
        self.show_box.currentIndexChanged.connect(self._fill)
        row.addWidget(self.show_box)
        ll.addLayout(row)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._pick)
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        b = QPushButton("⟳ Refresh list")
        b.clicked.connect(lambda: self.refresh(force=True))
        row.addWidget(b)
        b = QPushButton("📤 Post my mod…")
        b.setToolTip("Put one of your mods on the list for everyone (it's reviewed first)")
        b.clicked.connect(self.post)
        row.addWidget(b)
        b = QPushButton("📬 My posts")
        b.setToolTip("Your posts: waiting for review, published or declined")
        b.clicked.connect(self.my_posts)
        row.addWidget(b)
        ll.addLayout(row)
        row = QHBoxLayout()
        self.who = QLabel("")
        self.who.setObjectName("muted")
        self.who.setWordWrap(True)
        row.addWidget(self.who, 1)
        self.b_review = QPushButton("🛡 Review posts")
        self.b_review.setToolTip("The posts waiting for review (the list's maintainers)")
        self.b_review.clicked.connect(self.review)
        self.b_review.setVisible(False)
        row.addWidget(self.b_review)
        self.b_out = QPushButton("Sign out")
        self.b_out.clicked.connect(self.sign_out)
        self.b_out.setVisible(False)
        row.addWidget(self.b_out)
        ll.addLayout(row)
        self._maint = False
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setMinimumHeight(220)
        self.picture.setObjectName("muted")
        rl.addWidget(self.picture, 2)
        self.title = QLabel("")
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        rl.addWidget(self.title)
        self.facts = QLabel("")
        self.facts.setObjectName("muted")
        self.facts.setWordWrap(True)
        rl.addWidget(self.facts)
        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setTextFormat(Qt.TextFormat.PlainText)
        self.desc.setAlignment(Qt.AlignmentFlag.AlignTop)
        rl.addWidget(self.desc, 1)
        self.notes = QLabel("")
        self.notes.setWordWrap(True)
        self.notes.setTextFormat(Qt.TextFormat.RichText)
        rl.addWidget(self.notes)
        row = QHBoxLayout()
        self.b_install = QPushButton("⬇ Install")
        self.b_install.clicked.connect(self.install)
        row.addWidget(self.b_install)
        self.b_page = QPushButton("🌐 Mod's page")
        self.b_page.clicked.connect(lambda: self.entry and self.entry.get("page") and webbrowser.open(self.entry["page"]))
        row.addWidget(self.b_page)
        row.addStretch(1)
        self.b_remove = QPushButton("Take off the list…")
        self.b_remove.setToolTip("Maintainers: remove this mod from the list (players who have it keep it)")
        self.b_remove.clicked.connect(self.remove_listing)
        self.b_remove.setVisible(False)
        row.addWidget(self.b_remove)
        rl.addLayout(row)
        split.addWidget(right)
        split.setSizes([380, 620])
        lay.addWidget(split, 1)
        self._show(None)

    # ---------------------------------------------------------------- the list
    def on_show(self):
        if self.index is None and not self._loading:
            self.refresh()
            self._account()
        else:
            self._fill()

    def refresh(self, force=False):
        if self._loading:
            return
        self._loading = True
        self.banner.show_text("Getting the mod list…")
        self._w = w = Worker(modindex.fetch_index, self.cache)

        def done(idx):
            self._loading = False
            self.index = idx
            n = len(idx["mods"])
            if idx.get("offline"):
                self.banner.show_text(f"The mod list couldn't be reached ({idx.get('error', '')[:120]}): showing the "
                                      f"copy from the last time ({n} mods).", warn=True)
            else:
                self.banner.show_text(f"{n} mod{'s' if n != 1 else ''} on the list. Want yours here? "
                                      "<b>📤 Post my mod…</b>")
            self._fill()

        def failed(msg):
            self._loading = False
            self.index = {"mods": []}
            self.banner.show_text("The mod list couldn't be reached: " + msg.splitlines()[0][:200], warn=True)
            self._fill()
        w.done.connect(done)
        w.failed.connect(failed)
        w.start()

    def _fill(self, *_):
        if self.index is None:
            return
        mods = self.ws.mods.all_mods()
        q = self.search.text().strip().lower()
        cat, show = self.category.currentData(), self.show_box.currentData()
        cur = self.entry.get("uid") if self.entry else None
        self.list.blockSignals(True)
        self.list.clear()
        for e in sorted(self.index["mods"], key=lambda e: (e.get("name") or "").lower()):
            st, _ = modindex.installed_state(e, mods)
            if cat and e.get("category") != cat:
                continue
            if show == "new" and st != "new" or show == "update" and st != "update" or \
                    show == "installed" and st not in ("installed", "newer", "update"):
                continue
            hay = " ".join([e.get("name", ""), e.get("author", ""), e.get("summary", ""),
                            " ".join(e.get("tags") or [])]).lower()
            if q and q not in hay:
                continue
            label = f"{e['name']}  ·  v{e['version']}  ·  {e['author']}"
            if STATE_TEXT[st]:
                label += f"     {STATE_TEXT[st]}"
            it = QListWidgetItem(label)
            it.setData(ROLE, e)
            it.setToolTip(e.get("summary", ""))
            self.list.addItem(it)
            if e.get("uid") == cur:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None:
            if self.list.count():
                self.list.setCurrentRow(0)
            else:
                self._show(None)
        self._pick(self.list.currentItem())

    def _pick(self, it, *_):
        self._show(it.data(ROLE) if it is not None else None)

    def _names(self):
        listed = {e["uid"]: e["name"] for e in (self.index or {}).get("mods", [])}
        mine = {m.meta.get("uid"): m.name for m in self.ws.mods.all_mods() if m.meta.get("uid")}
        return listed, mine

    def _show(self, e):
        self.entry = e
        self.b_remove.setVisible(bool(e) and self._maint)
        for w in (self.b_install, self.b_page):
            w.setEnabled(bool(e))
        if not e:
            self.picture.setText("Pick a mod on the left." if self.index is not None and self.index["mods"]
                                 else "No mods to show yet.")
            self.picture.setPixmap(QPixmap())
            for w in (self.title, self.facts, self.desc, self.notes):
                w.setText("")
            self.b_page.setVisible(False)
            return
        st, mine = modindex.installed_state(e, self.ws.mods.all_mods())
        self.title.setText(f"{e['name']}  v{e['version']}")
        size = int(e.get("size", 0))
        self.facts.setText(" · ".join(x for x in (
            f"by {e['author']}", e.get("category", ""), f"{size / 1048576:.1f} MB" if size >= 1 << 20 else
            f"{size // 1024 + 1} KB", f"updated {e['updated']}" if e.get("updated") else "",
            ", ".join(e.get("tags") or [])) if x))
        self.desc.setText((e.get("summary", "") + "\n\n" + e.get("description", "")).strip())
        notes = []
        listed, have = self._names()
        req = [u for u in e.get("requires") or [] if u not in have]
        if req:
            notes.append("Needs: " + ", ".join(listed.get(u, "a mod that isn't on the list") for u in req) +
                         (" (installed with it)" if all(u in listed for u in req) else ""))
        if modindex.kit_too_old(e, VERSION):
            notes.append(f"<span style='color:#f0b35a'>Made for D5 Mod Kit {e['kit']} or newer: update the kit "
                         "first (Home).</span>")
        if mine is not None:
            notes.append(f"Installed here as '{mine.name}' v{mine.meta.get('version', '?')}.")
        self.notes.setText("<br>".join(notes))
        self.b_install.setText({"new": "⬇ Install", "update": f"⬆ Update to v{e['version']}",
                                "installed": "⟳ Install again", "newer": "⬇ Install this version"}[st])
        self.b_install.setEnabled(not modindex.kit_too_old(e, VERSION))
        self.b_page.setVisible(bool(e.get("page")))
        self.picture.setText("…")
        self.picture.setPixmap(QPixmap())
        uid = e.get("uid")
        self._pw = w = Worker(modindex.preview, e, self.cache)

        def shown(data):
            if not self.entry or self.entry.get("uid") != uid:
                return
            pm = QPixmap()
            if data and pm.loadFromData(data):
                self.picture.setPixmap(pm.scaled(self.picture.width(), max(200, self.picture.height()),
                                                 Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
                self.picture.setText("")
            else:
                self.picture.setText("(no picture)")
        w.done.connect(shown)
        w.failed.connect(lambda _m: self.picture.setText("(no picture)"))
        w.start()

    # ---------------------------------------------------------------- installing
    def install(self):
        e = self.entry
        if not e:
            return
        listed, have = self._names()
        by_uid = {x["uid"]: x for x in self.index["mods"]}
        chain = [by_uid[u] for u in e.get("requires") or [] if u not in have and u in by_uid] + [e]
        missing = [u for u in e.get("requires") or [] if u not in have and u not in by_uid]
        if missing and QMessageBox.question(
                self, "Install", f"'{e['name']}' needs {len(missing)} mod(s) that aren't on the list or here: it "
                "may not work without them. Install it anyway?") != QMessageBox.StandardButton.Yes:
            return
        self.install_chain(chain)

    def install_chain(self, chain, checked=True):
        """download and import these entries in order (checked=False: a post not reviewed yet, for its reviewer)"""
        total = sum(int(x["size"]) for x in chain)
        what = ", ".join(f"'{x['name']}'" for x in chain)
        note = ("The download is checked against the mod list before it is imported." if checked else
                "It isn't reviewed yet: the download is checked against its post, and the package checks keep out "
                "anything that isn't mod data.")
        if QMessageBox.question(self, "Install", f"Download and import {what} ({total / 1048576:.1f} MB)?\n\n"
                                f"{note} A mod you already have is updated and its old version kept as a backup.") \
                != QMessageBox.StandardButton.Yes:
            return
        self._chain = list(chain)
        self._done = []
        self._next()

    def _next(self):
        if not self._chain:
            return self._finished()
        e = self._chain.pop(0)
        prog = QProgressDialog(f"Downloading '{e['name']}'…", "Cancel", 0, 1000, self)
        prog.setWindowTitle("Browse Mods")
        prog.setMinimumDuration(0)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        state = {"done": 0, "total": int(e["size"]), "cancel": False}

        def progress(done, total):
            state["done"], state["total"] = done, total
            if state["cancel"]:
                raise RuntimeError("cancelled")
        folder = tempfile.mkdtemp(prefix="d5browse_")
        self._dw = w = Worker(modindex.download, e, folder, progress)
        timer = QTimer(self)
        timer.timeout.connect(lambda: prog.setValue(int(1000 * state["done"] / max(1, state["total"]))))
        timer.start(150)
        prog.canceled.connect(lambda: state.__setitem__("cancel", True))

        def close():
            timer.stop()
            prog.canceled.disconnect()            # (closing the dialog would count as Cancel)
            prog.close()

        def done(path):
            close()
            self._import(e, path)

        def failed(msg):
            cancelled = state["cancel"]
            close()
            self._chain = []
            if not cancelled:
                error_box(self, f"Could not install '{e['name']}'", msg.split("\n\n")[0])
        w.done.connect(done)
        w.failed.connect(failed)
        w.start()

    def _import(self, e, path):
        lines = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = modshare.import_package(path, self.ws.mods.mods_dir, self.ws.fs,
                                          os.path.join(os.path.dirname(self.ws.mods.mods_dir), "state"),
                                          log=lines.append)
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            self._chain = []
            return error_box(self, f"Could not import '{e['name']}'", ex)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        QApplication.restoreOverrideCursor()
        for line in lines:
            self.ws.log(line)
        self._done.append((e, res))
        self._next()

    def _finished(self):
        if not self._done:
            return
        self.ws.mods_changed.emit()
        parts = []
        for e, res in self._done:
            t = f"{'Updated' if res['update'] else 'Installed'} '{e['name']}' v{e['version']}"
            if res.get("moved"):
                t += " (some of its ids were moved: they clashed with your other mods)"
            parts.append(t + ".")
        QMessageBox.information(self, "Browse Mods", "\n".join(parts) + "\n\nIt is switched on: press Install "
                                "(bottom left) to put it into the game.")
        self._done = []
        self._fill()

    # ---------------------------------------------------------------- the account, posting, review
    def _kit_dir(self):
        return os.path.dirname(self.ws.mods.mods_dir)

    def github(self, ask=True):
        """a signed-in GitHub client, or None (ask: sign in when there is no sign-in yet)"""
        tok = modpost.load_token(self._kit_dir())
        if not tok and ask:
            dlg = SignInDialog(self.ws, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return None
            tok = modpost.load_token(self._kit_dir())
        return modpost.GitHub(tok) if tok else None

    def _account(self):
        """the account line and the maintainer's Review button"""
        tok = modpost.load_token(self._kit_dir())
        if not tok:
            self.who.setText("Not signed in. Posting a mod asks you to sign in with GitHub once (a free account).")
            self.b_out.setVisible(False)
            self.b_review.setVisible(False)
            return
        self.who.setText("Signed in…")
        self._aw = w = Worker(lambda: (lambda g: (g.login(), g.can_maintain()))(modpost.GitHub(tok)))

        def done(r):
            login, maint = r
            self.who.setText(f"Signed in with GitHub as <b>{login}</b>" + (" (you look after the list)" if maint
                                                                           else ""))
            self.b_out.setVisible(True)
            self.b_review.setVisible(maint)
            self.b_remove.setVisible(maint and self.entry is not None)
            self._maint = maint
        w.done.connect(done)
        w.failed.connect(lambda m: self.who.setText("The GitHub sign-in didn't work: sign in again when you post."))
        w.start()

    def sign_out(self):
        modpost.sign_out(self._kit_dir())
        self._maint = False
        self._account()

    def post(self):
        if not modpost.client_id(self.ws.settings):
            return QMessageBox.information(self, "Post my mod", "Posting isn't switched on in this copy of the kit "
                                           "yet. Update the kit (Home), or share the mod as a .zip (Home › right-"
                                           "click › Share).")
        gh = self.github()
        if gh is None:
            return
        PostDialog(self.ws, gh, self.index or {"mods": []}, self).exec()
        self._account()

    def my_posts(self):
        gh = self.github()
        if gh is not None:
            MyPostsDialog(gh, self).exec()

    def review(self):
        gh = self.github(ask=False)
        if gh is not None:
            ReviewDialog(self.ws, gh, self).exec()
            self.refresh(force=True)

    def remove_listing(self):
        e = self.entry
        gh = self.github(ask=False)
        if not e or gh is None:
            return
        from PyQt6.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getText(self, "Take off the list", f"Take '{e['name']}' off the mod list? "
                                          "Players who have it keep it. Reason (optional, shown in the list's "
                                          "history):")
        if not ok:
            return
        try:
            modpost.remove_listing(gh, e["uid"], reason.strip())
        except Exception as ex:
            return error_box(self, "Take off the list", ex)
        QMessageBox.information(self, "Take off the list", f"'{e['name']}' is off the list.")
        self.refresh(force=True)


def _busy(parent, title, fn, done, *args):
    """run fn(*args, progress) in the background with a progress window; done(result) on success"""
    prog = QProgressDialog("…", None, 0, 0, parent)
    prog.setWindowTitle(title)
    prog.setMinimumDuration(0)
    prog.setWindowModality(Qt.WindowModality.WindowModal)
    prog.show()
    state = {"text": "…"}
    w = Worker(fn, *args, lambda t: state.__setitem__("text", t))
    timer = QTimer(parent)
    timer.timeout.connect(lambda: prog.setLabelText(state["text"]))
    timer.start(200)

    def ok(r):
        timer.stop()
        prog.close()
        done(r)

    def bad(msg):
        timer.stop()
        prog.close()
        error_box(parent, title, msg.split("\n\n")[0])
    w.done.connect(ok)
    w.failed.connect(bad)
    w.start()
    parent._busy_worker = w


class SignInDialog(QDialog):
    """GitHub's device sign-in: a code to type on github.com, nothing else"""

    def __init__(self, ws, parent=None):
        super().__init__(parent)
        self.ws = ws
        self.kit_dir = os.path.dirname(ws.mods.mods_dir)
        self.setWindowTitle("Sign in to post mods")
        self.resize(520, 330)
        lay = QVBoxLayout(self)
        t = QLabel("Mods are posted on GitHub, where the mod list lives. You need a free GitHub account; the kit "
                   "does everything else. Sign in once on this PC:<br><br>1. Press <b>Open GitHub</b> (the code "
                   "is copied for you).<br>2. Paste the code on the page that opens and press Continue, then "
                   "<b>Authorize</b>. No account yet? That page has <i>Create an account</i>.<br>3. Come back here: "
                   "it signs you in by itself.")
        t.setWordWrap(True)
        lay.addWidget(t)
        self.code = QLabel("…")
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.code.setStyleSheet("font-size: 28px; font-weight: 700; letter-spacing: 4px; padding: 10px;")
        lay.addWidget(self.code)
        self.status = QLabel("Asking GitHub for a code…")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        self.b_open = QPushButton("🌐 Open GitHub")
        self.b_open.setEnabled(False)
        self.b_open.clicked.connect(self._open)
        row.addWidget(self.b_open)
        row.addStretch(1)
        b = QPushButton("Cancel")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        lay.addLayout(row)
        self._cancel = False
        self.start = None
        self.cid = modpost.client_id(ws.settings)
        self._w = w = Worker(modpost.device_start, self.cid)
        w.done.connect(self._started)
        w.failed.connect(lambda m: self.status.setText("GitHub couldn't be reached: " + m.splitlines()[0]))
        w.start()

    def _started(self, d):
        self.start = d
        self.code.setText(d["user_code"])
        self.b_open.setEnabled(True)
        self.status.setText("Waiting for you to allow it on GitHub…")
        self._ww = w = Worker(modpost.device_wait, self.cid, d, lambda: self._cancel)
        w.done.connect(self._token)
        w.failed.connect(lambda m: self.status.setText("Sign-in failed: " + m.splitlines()[0]))
        w.start()

    def _open(self):
        QApplication.clipboard().setText(self.start["user_code"])
        webbrowser.open(self.start.get("verification_uri", "https://github.com/login/device"))

    def _token(self, tok):
        if not tok:
            if not self._cancel:
                self.status.setText("The code ran out of time: close this and try again.")
            return
        modpost.save_token(self.kit_dir, tok)
        self.accept()

    def reject(self):
        self._cancel = True
        super().reject()


class PostDialog(QDialog):
    """put one of your mods on the list: fill in, press Post"""

    def __init__(self, ws, gh, index, parent=None):
        super().__init__(parent)
        self.ws, self.gh, self.index = ws, gh, index
        self.picture_path = None
        self.setWindowTitle("Post my mod")
        self.resize(720, 680)
        lay = QVBoxLayout(self)
        t = QLabel("Your mod goes to the mod list for review. Once it is published, everyone sees it on Browse "
                   "Mods. To post an <b>update</b>, post the same mod again with a higher version.")
        t.setWordWrap(True)
        lay.addWidget(t)
        f = QFormLayout()
        self.mod = QComboBox()
        for m in sorted(ws.mods.all_mods(), key=lambda m: m.name.lower()):
            if not m.meta.get("local_ids"):
                self.mod.addItem(m.name, m)
        f.addRow("Mod", self.mod)
        self.version = QLineEdit()
        self.author = QLineEdit(ws.settings.get("author", ""))
        self.category = QComboBox()
        self.category.addItems(modindex.CATEGORIES)
        self.summary = QLineEdit()
        self.summary.setPlaceholderText("One line: what it adds")
        self.description = QPlainTextEdit()
        self.description.setPlaceholderText("What's in it, how to get it in the game, what it needs …")
        self.description.setFixedHeight(100)
        pic = QHBoxLayout()
        self.pic = QLabel("No picture (a picture makes people look)")
        self.pic.setObjectName("muted")
        self.pic.setFixedHeight(90)
        pic.addWidget(self.pic, 1)
        b = QPushButton("Choose picture…")
        b.clicked.connect(self._choose_picture)
        pic.addWidget(b)
        self.mine = QCheckBox("This is my own work, or I have permission to share it (and I credit what it's based on)")
        for lab, w in (("Version", self.version), ("Your name", self.author), ("Kind", self.category),
                       ("Summary", self.summary), ("Description", self.description)):
            f.addRow(lab, w)
        f.addRow("Picture", pic)
        f.addRow(self.mine)
        lay.addLayout(f)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        lay.addStretch(1)
        bb = QDialogButtonBox()
        self.b_post = bb.addButton("📤 Post", QDialogButtonBox.ButtonRole.AcceptRole)
        self.b_post.clicked.connect(self._post)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)
        lay.addWidget(bb)
        self.mod.currentIndexChanged.connect(self._mod_changed)
        self._mod_changed()
        if not self.author.text():
            try:
                self.author.setText(gh.login())
            except Exception:
                pass

    def _listed(self, m):
        uid = m.meta.get("uid")
        return next((e for e in self.index.get("mods", []) if uid and e.get("uid") == uid), None)

    def _mod_changed(self, *_):
        m = self.mod.currentData()
        if m is None:
            return
        e = self._listed(m)
        if e:
            self.version.setText(_next_version(e.get("version", "1.0")))
            self.summary.setText(e.get("summary", ""))
            self.description.setPlainText(e.get("description", ""))
            i = self.category.findText(e.get("category", "Other"))
            self.category.setCurrentIndex(max(0, i))
            self.note.setText(f"'{e['name']}' v{e['version']} is on the list: this posts an update.")
        else:
            self.version.setText(str(m.meta.get("version") or "1.0"))
            self.summary.setText(m.meta.get("description", "")[:120])
            self.note.setText("")
        if m.meta.get("author"):
            self.author.setText(m.meta["author"])

    def _choose_picture(self):
        from PyQt6.QtWidgets import QFileDialog
        p, _ = QFileDialog.getOpenFileName(self, "Picture for the mod list", "",
                                           "Pictures (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not p:
            return
        try:
            data = modpost.make_preview(p)
        except Exception as e:
            return error_box(self, "Picture", e)
        self.picture_path = p
        self._preview = data
        pm = QPixmap()
        pm.loadFromData(data)
        self.pic.setPixmap(pm.scaledToHeight(90, Qt.TransformationMode.SmoothTransformation))

    def _post(self):
        m = self.mod.currentData()
        version = self.version.text().strip()
        if m is None or not version or not self.author.text().strip() or not self.summary.text().strip():
            return QMessageBox.information(self, "Post my mod", "Fill in the version, your name and the summary.")
        if not self.mine.isChecked():
            return QMessageBox.information(self, "Post my mod", "Tick the box that says it's your work (or that "
                                           "you have permission).")
        e = self._listed(m)
        if e and modindex._ver(version) <= modindex._ver(e.get("version", "0")):
            return QMessageBox.information(self, "Post my mod", f"The list has v{e['version']}: give this one a "
                                           "higher version to post it as an update.")
        name, author = m.name, self.author.text().strip()
        summary, desc, cat = self.summary.text().strip(), self.description.toPlainText().strip(), \
            self.category.currentText()
        preview = getattr(self, "_preview", None)
        folder = tempfile.mkdtemp(prefix="d5post_")
        zpath = os.path.join(folder, f"{modpost.slug(name)}_v{modpost.slug(version)}.zip")

        def work(progress):
            progress("Packing the mod…")
            modshare.export_package(m, zpath, version=version, author=author)
            entry = modindex.entry_for(m, "https://github.com/pending", zpath, category=cat, summary=summary,
                                       description=desc)
            return modpost.post(self.gh, zpath, entry, preview, progress)

        def done(url):
            self.ws.settings["author"] = author
            self.ws.save_settings()
            box = QMessageBox(self)
            box.setWindowTitle("Posted")
            box.setText(f"'{name}' v{version} is posted and waits for review. Once it is published it shows on "
                        "Browse Mods for everyone. <b>My posts</b> shows where it is.")
            box.exec()
            self.accept()
        _busy(self, "Post my mod", work, done)


def _next_version(v):
    parts = str(v or "1.0").split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        parts.append("1")
    return ".".join(parts)


class MyPostsDialog(QDialog):
    def __init__(self, gh, parent=None):
        super().__init__(parent)
        self.setWindowTitle("My posts")
        self.resize(620, 400)
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda it: webbrowser.open(it.data(ROLE)))
        lay.addWidget(self.list, 1)
        t = QLabel("Waiting = a reviewer will look at it soon. Double-click one to see the review (its comments "
                   "say what to change if it was declined).")
        t.setWordWrap(True)
        t.setObjectName("muted")
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.list.addItem("Loading…")
        self._w = w = Worker(modpost.my_posts, gh)
        w.done.connect(self._fill)
        w.failed.connect(lambda m: (self.list.clear(), self.list.addItem("Couldn't load: " + m.splitlines()[0])))
        w.start()

    def _fill(self, posts):
        self.list.clear()
        icon = {"waiting": "⏳ waiting for review", "published": "✔ published", "declined": "✖ declined"}
        for p in posts:
            it = QListWidgetItem(f"{p['title']}     {icon[p['state']]}")
            it.setData(ROLE, p["url"])
            self.list.addItem(it)
        if not posts:
            self.list.addItem("No posts yet.")


class ReviewDialog(QDialog):
    """for the list's maintainers: the waiting posts, try one, publish or decline it"""

    def __init__(self, ws, gh, page):
        super().__init__(page)
        self.ws, self.gh, self.page = ws, gh, page
        self.setWindowTitle("Review posts")
        self.resize(900, 560)
        lay = QVBoxLayout(self)
        split = QSplitter()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._pick)
        split.addWidget(self.list)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setAlignment(Qt.AlignmentFlag.AlignTop)
        rl.addWidget(self.info, 1)
        row = QHBoxLayout()
        self.b_try = QPushButton("⬇ Install to try")
        self.b_try.setToolTip("Download and import it here (with the same checks as Browse Mods), then test it in "
                              "the game")
        self.b_try.clicked.connect(self._try)
        row.addWidget(self.b_try)
        self.b_pub = QPushButton("✔ Publish")
        self.b_pub.clicked.connect(self._publish)
        row.addWidget(self.b_pub)
        self.b_dec = QPushButton("✖ Decline…")
        self.b_dec.clicked.connect(self._decline)
        row.addWidget(self.b_dec)
        b = QPushButton("🌐 On GitHub")
        b.clicked.connect(lambda: self.item and webbrowser.open(self.item["url"]))
        row.addWidget(b)
        rl.addLayout(row)
        split.addWidget(right)
        split.setSizes([320, 580])
        lay.addWidget(split, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.item = None
        self.load()

    def load(self):
        self.list.clear()
        self.list.addItem("Loading…")
        self._w = w = Worker(modpost.submissions, self.gh)
        w.done.connect(self._fill)
        w.failed.connect(lambda m: (self.list.clear(), self.list.addItem("Couldn't load: " + m.splitlines()[0])))
        w.start()

    def _fill(self, subs):
        self.list.clear()
        mark = {"passed": "✔", "failed": "✖", "running": "…", "none": "?"}
        for s in subs:
            it = QListWidgetItem(f"{mark[s['check']]}  {s['title']}  ·  {s['author']}")
            it.setData(ROLE, s)
            self.list.addItem(it)
        if not subs:
            self.list.addItem("Nothing waiting.")
            self._pick(None)
        else:
            self.list.setCurrentRow(0)

    def _pick(self, it, *_):
        s = it.data(ROLE) if it is not None else None
        self.item = s if isinstance(s, dict) else None
        for b in (self.b_try, self.b_pub, self.b_dec):
            b.setEnabled(self.item is not None)
        if not self.item:
            self.info.setText("")
            return
        s = self.item
        check = {"passed": "<span style='color:#7ad67a'>passed</span>", "failed":
                 "<span style='color:#ff6b6b'>FAILED (open it on GitHub for why)</span>", "running": "still running",
                 "none": "not run"}[s["check"]]
        rows = [f"<b>{s['title']}</b> by {s['author']}", f"Automatic check: {check}"]
        for e in s["entries"]:
            rows.append(f"<br><b>{e.get('name')}</b> v{e.get('version')} ({e.get('category', '')}, "
                        f"{int(e.get('size', 0)) / 1048576:.1f} MB) by {e.get('author')}<br>{e.get('summary', '')}"
                        f"<br><i>{e.get('description', '')}</i>")
        if s["removed"]:
            rows.append(f"<br><span style='color:#f0b35a'>It also takes {len(s['removed'])} mod(s) off the list."
                        "</span>")
        for fl in s["flags"]:
            rows.append(f"<span style='color:#f0b35a'>⚠ {fl}</span>")
        rows.append("<br>Before publishing: install it to try, look at it in the game (it's checked to be data "
                    "only), then Publish. Decline with a short reason: the poster sees it.")
        self.info.setText("<br>".join(rows))
        self.b_try.setEnabled(bool(s["entries"]))

    def _try(self):
        if self.item and self.item["entries"]:
            self.page.install_chain(list(self.item["entries"]), checked=False)

    def _publish(self):
        s = self.item
        if not s:
            return
        warn = "" if s["check"] == "passed" else "\n\nThe automatic check didn't pass."
        if QMessageBox.question(self, "Publish", f"Publish '{s['title']}'? It shows on everyone's Browse Mods."
                                + warn) != QMessageBox.StandardButton.Yes:
            return
        try:
            modpost.publish(self.gh, s["number"])
        except Exception as e:
            return error_box(self, "Publish", e)
        QMessageBox.information(self, "Publish", "Published.")
        self.load()

    def _decline(self):
        s = self.item
        if not s:
            return
        from PyQt6.QtWidgets import QInputDialog
        reason, ok = QInputDialog.getMultiLineText(self, "Decline", "Why (the poster sees this; say what to "
                                                   "change if it can be fixed):")
        if not ok:
            return
        try:
            modpost.decline(self.gh, s["number"], reason.strip())
        except Exception as e:
            return error_box(self, "Decline", e)
        self.load()
