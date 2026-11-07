"""Diccionario local: frecuencias agregadas y hasta dos palabras de contexto."""
from functools import lru_cache
import hashlib
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

from app_paths import RESOURCE_ROOT
from profiles import validate_user_id

WORD = re.compile(r"[^\W\d_][^\W_]{0,39}", re.UNICODE)


def key(word):
    return unicodedata.normalize("NFC", word).casefold()


@lru_cache(maxsize=1)
def base_words():
    return tuple(dict.fromkeys((RESOURCE_ROOT / "assets/keyboard-es.txt").read_text(encoding="utf-8").split()))


def one_edit(a, b):
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) != len(b):
        short, long = sorted((a, b), key=len)
        i = next((i for i, char in enumerate(short) if char != long[i]), len(short))
        return short[i:] == long[i+1:]
    differences = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(differences) == 1:
        return True
    if len(differences) == 2:
        i, j = differences
        return j == i + 1 and a[i] == b[j] and a[j] == b[i]
    return False


class Dictionary:
    def __init__(self, root, profile, clock=time.time):
        folder = Path(root) / "keyboard"
        folder.mkdir(parents=True, exist_ok=True)
        filename=hashlib.sha256(validate_user_id(profile).encode()).hexdigest()
        self.db = sqlite3.connect(folder / (filename + ".sqlite3"), timeout=.2)
        self.clock = clock
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            PRAGMA secure_delete=ON;
            CREATE TABLE IF NOT EXISTS words(
                word TEXT PRIMARY KEY, spelling TEXT NOT NULL, uses INTEGER NOT NULL, recent INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS grams(
                first TEXT NOT NULL, second TEXT NOT NULL, word TEXT REFERENCES words ON DELETE CASCADE,
                uses INTEGER NOT NULL, PRIMARY KEY(first,second,word)
            );
        """)

    def close(self):
        self.db.close()

    def learn(self, spelling, context):
        spelling = unicodedata.normalize("NFC", spelling)
        if not WORD.fullmatch(spelling):
            return
        word = key(spelling)
        with self.db:
            self.db.execute("""INSERT INTO words VALUES(?,?,1,?)
                ON CONFLICT(word) DO UPDATE SET spelling=excluded.spelling, uses=uses+1, recent=excluded.recent""",
                            (word, spelling, int(self.clock() // 3600)))
            pairs = [("", context[-1])] if context else []
            if len(context) >= 2:
                pairs.append((context[-2], context[-1]))
            for first, second in pairs:
                self.db.execute("""INSERT INTO grams VALUES(?,?,?,1)
                    ON CONFLICT(first,second,word) DO UPDATE SET uses=uses+1""",
                                (key(first), key(second), word))
            # Los límites contienen el tamaño y evitan acumular contexto indefinidamente.
            self.db.execute("""DELETE FROM words WHERE word IN
                (SELECT word FROM words ORDER BY uses DESC,recent DESC,word LIMIT -1 OFFSET 5000)""")
            self.db.execute("""DELETE FROM grams WHERE rowid IN
                (SELECT rowid FROM grams ORDER BY uses DESC,rowid DESC LIMIT -1 OFFSET 12000)""")

    def words(self):
        return [r[0] for r in self.db.execute("SELECT spelling FROM words ORDER BY word")]

    def delete(self, spelling):
        word = key(spelling)
        with self.db:
            self.db.execute("DELETE FROM grams WHERE first=? OR second=?", (word, word))
            self.db.execute("DELETE FROM words WHERE word=?", (word,))

    def clear(self):
        with self.db:
            self.db.execute("DELETE FROM grams")
            self.db.execute("DELETE FROM words")

    def suggest(self, prefix, context, corrections=False):
        normalized = key(prefix)
        high = normalized + "\U0010ffff"
        rows = self.db.execute("""SELECT word,spelling,uses,recent FROM words
            WHERE word>=? AND word<? ORDER BY uses DESC,recent DESC LIMIT 48""", (normalized, high))
        now = int(self.clock() // 3600)
        scores = {word: (spelling, uses * 4 + max(0, 3 - (now - recent) / 48))
                  for word, spelling, uses, recent in rows}
        if context:
            pairs = [("", key(context[-1]), 12)]
            if len(context) > 1:
                pairs.append((key(context[-2]), key(context[-1]), 24))
            for first, second, weight in pairs:
                rows = self.db.execute("""SELECT w.word,w.spelling,g.uses FROM grams g JOIN words w USING(word)
                    WHERE g.first=? AND g.second=? AND w.word>=? AND w.word<?
                    ORDER BY g.uses DESC LIMIT 24""", (first, second, normalized, high))
                for word, spelling, uses in rows:
                    scores[word] = (spelling, scores.get(word, (spelling, 4))[1] + weight * uses)
        for rank, word in enumerate(base_words()):
            if key(word).startswith(normalized):
                scores.setdefault(key(word), (word, 1 / (rank + 1)))
        scores.pop(normalized, None)
        predictions = [(word, False) for word, score in sorted(scores.values(), key=lambda x: (-x[1], key(x[0])))[:3]]
        if corrections and 3 <= len(prefix) <= 24 and prefix.islower() and prefix.isalpha():
            known = self.db.execute("SELECT 1 FROM words WHERE word=?", (normalized,)).fetchone()
            if not known and normalized not in base_words() and len(predictions) < 3:
                predictions += [(word, True) for word in base_words()
                                if not word.startswith(normalized) and one_edit(normalized, word)][:3-len(predictions)]
        return predictions
