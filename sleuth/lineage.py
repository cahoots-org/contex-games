"""Id generation and line ancestry tracking."""

from collections import defaultdict


class Ids:
    def __init__(self) -> None:
        self._counts: dict[str, int] = defaultdict(int)

    def next(self, prefix: str) -> str:
        self._counts[prefix] += 1
        return f"{prefix}-{self._counts[prefix]}"

    def ensure_past(self, prefix: str, n: int) -> None:
        """Make the next id for prefix come after n."""
        self._counts[prefix] = max(self._counts[prefix], n)

    def to_state(self) -> dict:
        """The counter for each prefix."""
        return dict(self._counts)

    def restore(self, state: dict) -> None:
        """Replace the counters with a saved state."""
        self._counts = defaultdict(int, state)


class Lineage:
    def __init__(self) -> None:
        self._parent: dict[str, str | None] = {}

    def record(self, uid: str, parent: str | None) -> None:
        """Record uid's parent."""
        self._parent[uid] = parent

    def to_state(self) -> dict:
        """Parents as plain JSON."""
        return {"parent": dict(self._parent)}

    def restore(self, state: dict) -> None:
        """Replace parents with a saved state."""
        self._parent = dict(state["parent"])

    def root(self, uid: str) -> str:
        while self._parent.get(uid) is not None:
            uid = self._parent[uid]
        return uid

    def depth(self, uid: str) -> int:
        """Hops between uid and its root."""
        n = 0
        while self._parent.get(uid) is not None:
            uid, n = self._parent[uid], n + 1
        return n

