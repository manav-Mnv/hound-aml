# FalkorDB 6.0.1 behaviours found while building Hound

Environment: FalkorDB 6.0.1 module (`falkordb-x64.so`, Rust engine) on Redis 8.0.5, Python client `falkordb` 1.8.0.

## 1. Variable-length path + `WHERE` on an `UNWIND` variable returns no rows

```python
from falkordb import FalkorDB
g = FalkorDB().select_graph("repro")
g.query("CREATE (:A {id:'a'})-[:R]->(:A {id:'b'})-[:R]->(:A {id:'c'})")
g.query("UNWIND ['c'] AS tid MATCH p = (o:A)-[:R*1..2]->(t:A) WHERE t.id = tid RETURN o.id").result_set
# []            <- expected [['b'], ['a']]
g.query("MATCH p = (o:A)-[:R*1..2]->(t:A) WHERE t.id = 'c' RETURN o.id").result_set
# [['b'], ['a']]
g.query("UNWIND ['c'] AS tid MATCH (t:A) WHERE t.id = tid MATCH p = (o:A)-[:R*1..2]->(t) RETURN o.id").result_set
# [['b'], ['a']]  <- workaround
```

## 2. A `collect()` column returns the row count

Seen in this query shape (not reproduced in a minimal graph yet):

```cypher
MATCH (a:Account {id: $id})-[t:TRANSFER]-(x:Account)
WHERE t.channel <> 'card'
OPTIONAL MATCH (h:Party)-[:HOLDS]->(x)
WITH x, h, CASE WHEN startNode(t) = a THEN 'out' ELSE 'in' END AS dir, t
RETURN dir, x.id, h.id, count(t) AS n, sum(t.amount) AS total,
       collect(DISTINCT t.channel) AS channels, collect(DISTINCT t.memo) AS memos, h.onboarded
```

`memos` came back as an integer equal to `n` (also without `DISTINCT`). Aggregating before the `OPTIONAL MATCH` returns correct lists.

## Also noted

- `shortestPath` is only allowed in `WITH`/`RETURN` (documented behaviour).
- `exists((a)-[:R]->(b))` with a pattern argument is rejected; pattern predicates elsewhere work.
- An inline property map that references another variable's property in a following `MATCH` (`MATCH (a) MATCH (j {code: a.country})`) raised "Variable a not found"; `WHERE j.code = a.country` works.
