"""In-memory stand-ins used ONLY by the offline tests (no network, no Supabase, no SWMM engine)."""
import math
import sys
import types
from datetime import datetime, timezone

PK = {"road_risk": "segment", "repair_tickets": "segment", "service_status": "service",
      "subscribers": "chat_id", "nodes": "id"}


class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self._order, self._limit = db, table, [], None, None
        self.op, self.payload = "select", None

    # filters
    def select(self, *_a, **_k): self.op = "select"; return self
    def eq(self, k, v): self.filters.append(lambda r: r.get(k) == v); return self
    def gt(self, k, v): self.filters.append(lambda r: r.get(k) is not None and r.get(k) > v); return self
    def gte(self, k, v): self.filters.append(lambda r: r.get(k) is not None and str(r.get(k)) >= str(v)); return self
    def order(self, k, desc=False): self._order = (k, desc); return self
    def limit(self, n): self._limit = n; return self

    # writes
    def insert(self, rows): self.op, self.payload = "insert", rows; return self
    def upsert(self, rows, on_conflict=None): self.op, self.payload = "upsert", rows; return self
    def update(self, vals): self.op, self.payload = "update", vals; return self
    def delete(self): self.op = "delete"; return self

    def _match(self):
        return [r for r in self.db.tables.setdefault(self.table, []) if all(f(r) for f in self.filters)]

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "select":
            out = self._match()
            if self._order:
                k, desc = self._order
                out = sorted(out, key=lambda r: (r.get(k) is None, r.get(k)), reverse=desc)
            return _Res([dict(r) for r in out[: self._limit or None]])
        if self.op in ("insert", "upsert"):
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            for it in items:
                it = dict(it)
                if self.table == "alerts" and it.get("dedupe_key") and any(
                        r.get("dedupe_key") == it["dedupe_key"] for r in rows):
                    raise Exception('duplicate key value violates unique constraint "alerts_dedupe_key"')
                pk = PK.get(self.table)
                existing = next((r for r in rows if pk and r.get(pk) == it.get(pk)), None)
                if self.op == "upsert" and existing:
                    existing.update(it)
                    continue
                self.db.seq += 1
                it.setdefault("id", self.db.seq)
                it.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                if self.table == "repair_tickets":
                    it.setdefault("status", "Reported")
                rows.append(it)
            return _Res(items)
        if self.op == "update":
            for r in self._match():
                r.update(self.payload)
            return _Res([])
        if self.op == "delete":
            keep = [r for r in rows if not all(f(r) for f in self.filters)]
            self.db.tables[self.table] = keep
            return _Res([])


class FakeDB:
    def __init__(self):
        self.tables, self.seq = {}, 0

    def table(self, name):
        return _Query(self, name)


# ----------------------------------------------------------------- fake pyswmm
class _Gate:
    def __init__(self):
        self.target_setting = 1.0


class _Node:
    def __init__(self, sim, name):
        self.sim, self.name = sim, name

    @property
    def depth(self):
        return min(1.5, self.sim.inflow(self.name) / 600.0)

    @property
    def flooding(self):
        return self.sim.flood.get(self.name, 0.0)

    @property
    def volume(self):
        return self.sim.pit.get(self.name, 0.0)


class FakeSimulation:
    """Storm peaks at minute 90. Pipe below J2 carries 434 L/s; each pit holds 180 m3.
    Opening a gate early fills the pit before the peak - so timing matters, like the real model."""
    def __init__(self, inp):
        self.inp, self.links = inp, {}
        self.flood, self.pit = {}, {"PIT1": 0.0, "PIT2": 0.0}

    def __enter__(self):
        from datetime import datetime as dt
        self.start_time = self.current_time = dt(2026, 1, 1)
        return self

    def __exit__(self, *a):
        return False

    def step_advance(self, s):
        self.step = s

    def minute(self):
        return (self.current_time - self.start_time).total_seconds() / 60

    def inflow(self, n):
        peak = {"J1": 300, "J2": 900, "J3": 500, "J4": 400}.get(n, 0)
        return peak * math.exp(-((self.minute() - 90) / 25) ** 2)

    def __iter__(self):
        from datetime import timedelta
        for i in range(360):
            self.current_time = self.start_time + timedelta(minutes=i + 1)
            for gate, node, pit in (("OR1", "J2", "PIT1"), ("OR2", "J3", "PIT2")):
                excess = max(0.0, self.inflow(node) - 434.0)
                g = self.links.get(gate)
                divert = 0.0
                if g and g.target_setting > 0 and self.pit[pit] < 180:
                    divert = min(200.0, self.inflow(node), (180 - self.pit[pit]) * 1000 / 60)
                    self.pit[pit] += divert * 60 / 1000
                self.flood[node] = max(0.0, excess - divert)
            yield i


def install_fake_pyswmm():
    mod = types.ModuleType("pyswmm")
    mod.Simulation = FakeSimulation

    def Nodes(sim):
        class D(dict):
            def __missing__(self, k):
                return _Node(sim, k)
        return D()

    def Links(sim):
        class D(dict):
            def __missing__(self, k):
                sim.links.setdefault(k, _Gate())
                return sim.links[k]
        return D()
    mod.Nodes, mod.Links = Nodes, Links
    sys.modules["pyswmm"] = mod
