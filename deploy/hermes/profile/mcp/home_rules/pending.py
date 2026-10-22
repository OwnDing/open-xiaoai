"""Scenes and linkages that were checked and read back, waiting for the user's "好".

The agent does not see its earlier tool calls (xiaozhi forwards text only), so
after the user agreed it had to rebuild the arguments for a second, confirmed
home_rule_save. On 2026-10-22 it called the check again instead, while saying
it had saved. Now home_rule_save records each checked item here and
home_rule_confirm saves the latest batch exactly as it was read back.

A JSON file, so every Hermes process running this server sees the same list.
"""

import json
import os
import sys
import tempfile
import threading
import time

TTL_S = 600  # the user answers within minutes; older checks are forgotten
BATCH_S = 120  # items checked this close to the newest one were read back together


class Pending:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self._lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                items = json.load(f).get("items", [])
        except (OSError, ValueError, AttributeError):
            return []
        cutoff = self.clock() - TTL_S
        return [i for i in items if isinstance(i, dict) and i.get("checked_at", 0) >= cutoff]

    def _store(self, items):
        """Write atomically; False if the file cannot be written."""
        try:
            folder = os.path.dirname(self.path) or "."
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".pending-")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"items": items}, f, ensure_ascii=False)
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            print(f"home_rules: cannot write {self.path}: {e}", file=sys.stderr)
            return False

    def record(self, kind, name, args, saved=False):
        """A checked item (saved=True: saved at once, e.g. a one-shot linkage); False if not stored."""
        now = self.clock()
        name = name.strip()
        with self._lock:
            items = [i for i in self._load() if (i["kind"], i["name"]) != (kind, name)]
            items.append({"kind": kind, "name": name, "args": args, "checked_at": now,
                          "saved_at": now if saved else None})
            return self._store(items)

    def batch(self, names=None):
        """(items to save, items of that batch already saved).

        Without names: the unsaved items checked within BATCH_S of the newest
        unsaved one, so a check the user turned down earlier is not saved with
        a later one. With names: the items so named (or naming each other).
        """
        with self._lock:
            items = self._load()
        if names:
            wanted = [n.strip() for n in names if n and n.strip()]
            chosen = [i for i in items if any(n == i["name"] or n in i["name"] or i["name"] in n for n in wanted)]
        else:
            unsaved = [i for i in items if not i["saved_at"]]
            pool = unsaved or items
            newest = max((i["checked_at"] for i in pool), default=0)
            chosen = [i for i in pool if i["checked_at"] >= newest - BATCH_S]
        return [i for i in chosen if not i["saved_at"]], [i for i in chosen if i["saved_at"]]
