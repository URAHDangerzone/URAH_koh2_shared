"""Minimal reader for the game's DT def format (*.def), enough for settlement and province feature defs.

Covers: `def Key : Base`, `type key = value`, nested blocks, `delete key`, `extend Path`, dotted keys
(`Camels.spawn_chance = 0`), arrays `[a, b]`, strings, `$[...]` texts and comments. Later files merge
into earlier ones like the game does for mods: a statement on an existing key keeps the key's value,
type and base unless it gives new ones, and merges its children.
"""

from __future__ import annotations

import re
from pathlib import Path

TOKEN = re.compile(r"""
    (?P<skip>//[^\n]*|/\*.*?\*/|[ \t\r,;]+)
  | (?P<nl>\n)
  | (?P<text>\$\[.*?\])
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<arr>\[[^\]]*\])
  | (?P<punct>[{}=:])
  | (?P<word>(?:[^\s{}=:;,"\[\]/]|/(?![/*]))+)
""", re.S | re.X)


class Field:
    __slots__ = ("key", "type", "value", "base", "children", "is_def", "parent")

    def __init__(self, key, type_=None, value=None, base=None, is_def=False):
        self.key, self.type, self.value, self.base, self.is_def = key, type_, value, base, is_def
        self.children: dict[str, Field] = {}
        self.parent = None

    def __repr__(self):
        return f"Field({self.key!r}, type={self.type!r}, value={self.value!r}, base={self.base!r}, {len(self.children)} children)"

    def child(self, path: str):
        f = self
        for k in path.split("."):
            f = f.children.get(k)
            if f is None:
                return None
        return f


def tokens(text: str):
    for m in TOKEN.finditer(text):
        kind = m.lastgroup
        if kind == "skip":
            continue
        yield kind, m.group()


class Parser:
    def __init__(self, text: str):
        self.toks = list(tokens(text))
        self.i = 0

    def peek(self, skip_nl=False):
        j = self.i
        while skip_nl and j < len(self.toks) and self.toks[j][0] == "nl":
            j += 1
        return self.toks[j] if j < len(self.toks) else (None, None)

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def block(self, parent: Field):
        """Parse statements into parent until '}' or the end."""
        while self.i < len(self.toks):
            kind, val = self.next()
            if kind == "nl":
                continue
            if val == "}":
                return
            if kind == "punct":  # stray '{' / '=' / ':' (malformed line): skip, keep the nesting
                if val == "{":
                    self.block(Field("<stray>"))
                continue
            words = [val]
            while self.i < len(self.toks) and self.peek()[0] in ("word", "str") and self.peek()[1] not in "{}=:":
                words.append(self.next()[1])
            op = "delete" if words[0] == "delete" else "extend" if words[0] == "extend" else None
            is_def = words[0] == "def"
            if op or is_def:
                words = words[1:]
            base = value = None
            if self.peek()[1] == ":":
                self.next()
                base = self.next()[1]
            if self.peek()[1] == "=":
                self.next()
                parts = []
                while self.i < len(self.toks) and self.peek()[0] != "nl" and self.peek()[1] not in "{}":
                    parts.append(self.next()[1])
                value = " ".join(parts)
            if not words:
                continue
            key = words[-1]
            type_ = words[-2] if len(words) >= 2 else None
            if op == "delete":
                target = resolve(parent, key, create=False)
                if target is not None and target.parent is not None:
                    target.parent.children.pop(target.key, None)
                if self.peek(skip_nl=True)[1] == "{":  # `delete europe { ... }`: redefine
                    while self.peek()[0] == "nl":
                        self.next()
                    self.next()
                    f = resolve(parent, key, create=True)
                    self.block(f)
                continue
            f = resolve(parent, key, create=True)
            if type_ is not None:
                f.type = type_
            if value is not None:
                f.value = value
            if base is not None:
                f.base = base
            f.is_def = f.is_def or is_def
            if self.peek(skip_nl=True)[1] == "{":
                while self.peek()[0] == "nl":
                    self.next()
                self.next()
                self.block(f)


def resolve(parent: Field, key: str, create: bool):
    f = parent
    for k in key.split("."):
        c = f.children.get(k)
        if c is None:
            if not create:
                return None
            c = Field(k)
            c.parent = f
            f.children[k] = c
        f = c
    return f


def load(paths, root: Field | None = None) -> Field:
    """Merge the def files (in order) into one tree; returns the root."""
    root = root or Field("<root>")
    for p in paths:
        p = Path(p)
        text = p.read_text(encoding="utf-8-sig") if p.exists() else str(p)
        Parser(text).block(root)
    return root


def find(root: Field, def_key: str, name: str):
    """Field `name` of def `def_key`, following the `: Base` chain like DT.Field.FindChild."""
    seen = set()
    f = root.children.get(def_key)
    while f is not None and f.key not in seen:
        seen.add(f.key)
        c = f.child(name)
        if c is not None:
            return c
        f = root.children.get(f.base) if f.base else None
    return None


def number(value, default=0.0):
    if value is None:
        return default
    try:
        return float(str(value).split()[0].strip('"'))
    except ValueError:
        return default


def array(value) -> list[str]:
    v = (value or "").strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [x.strip() for x in v.split(",") if x.strip()]
