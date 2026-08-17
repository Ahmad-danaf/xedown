"""What a search of the rendered preview currently is.

Pure logic: no GTK, no DOM. `searchbar.py` displays what this decides and
`preview.js` marks what it asks for. Every question with an answer -- is this
a new search, which match is current, what does the label say, is this answer
still wanted -- is answered here, where the unit tests can reach it.
"""

# A query matching more than this is a filter, not a search. `preview.js`
# stops marking at the same number, and tests/unit/test_resources.py pins the
# two together: a page that stops wrapping at a different number than the
# label counts to is a disagreement nobody would see until a document was big
# enough to reach it.
MATCH_CAP = 2000

NO_MATCHES = "No matches"


def collapse(text):
    """The query as the page will see it: one space per run of whitespace.

    `preview.js` searches a flattened copy of the rendered text in which every
    run of whitespace is a single space, because that is what the reader sees
    -- HTML collapses the newline Python-Markdown leaves inside a paragraph
    the author wrapped over two source lines. A query has to be collapsed the
    same way or it could never match one.
    """
    return " ".join(text.split()) if text else ""


def status_text(total, index, capped):
    """The bar's label for one state of a search.

    `total` is None while no search is live, which is not the same as a search
    that found nothing: the first says nothing at all, the second says so.
    """
    if total is None:
        return ""
    if total <= 0:
        return NO_MATCHES
    counted = f"{MATCH_CAP}+" if capped else str(total)
    # `report` places the index on 0 whenever there are matches, so the max()
    # never fires; it is here so a caller that got the order wrong shows the
    # first match rather than "0 of 17".
    return f"{max(index, 0) + 1} of {counted}"


class SearchSession:
    """One tab's search: the query, the answer, and which match is current."""

    def __init__(self):
        self.case_sensitive = False
        self._token = 0
        self.clear()

    @property
    def token(self):
        """The generation the page's next answer must carry to be believed."""
        return self._token

    @property
    def active(self):
        return bool(self.query)

    def clear(self):
        """End the search. Deliberately keeps `case_sensitive`.

        The bar keeps its query text and its case toggle for the life of the
        tab, so forgetting the flag here would silently reset a preference the
        user can still see set. Bumping the token is what stops an answer
        already in flight from repopulating a count for a query that no longer
        exists.
        """
        self.query = ""
        self.total = None
        self.index = -1
        self.capped = False
        self._token += 1

    def invalidate(self):
        """Stop wanting answers for the query as it stands, and say so.

        Returns the new token. `clear()` bumps the token as part of ending
        the search; this bumps it while the search stays live, which is what
        the controller needs when it starts answering on the page's behalf:
        the page that would have replied is gone, and a reply of its already
        in flight must not be believed.
        """
        self._token += 1
        return self._token

    def set_query(self, text, case_sensitive):
        """Take a new query. True when the page has to be asked again."""
        collapsed = collapse(text)
        case_sensitive = bool(case_sensitive)
        if not collapsed:
            was_active = self.active
            self.case_sensitive = case_sensitive
            if not was_active:
                return False
            self.clear()
            return True
        if collapsed == self.query and case_sensitive == self.case_sensitive:
            return False
        self.query = collapsed
        self.case_sensitive = case_sensitive
        self.total = None
        self.index = -1
        self.capped = False
        self._token += 1
        return True

    def report(self, total, capped, token):
        """Take the page's answer. False when it is for a query since replaced.

        The index is placed rather than reset: a fresh search starts on the
        first match, and an edit that deletes the tail of the document moves
        `9 of 9` to `6 of 6` instead of jumping the reader back to the top.
        """
        if token != self._token or not self.active:
            return False
        try:
            self.total = max(0, int(total))
        except (TypeError, ValueError):
            self.total = 0
        self.capped = bool(capped)
        if self.total == 0:
            self.index = -1
        elif self.index < 0:
            self.index = 0
        else:
            self.index = min(self.index, self.total - 1)
        return True

    def step(self, forward):
        """The next or previous match, wrapping. None when there is none."""
        if not self.total:
            return None
        if self.index < 0:
            self.index = 0 if forward else self.total - 1
        else:
            self.index = (self.index + (1 if forward else -1)) % self.total
        return self.index

    def status(self):
        return status_text(self.total, self.index, self.capped)
