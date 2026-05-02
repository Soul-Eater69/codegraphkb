# Neo4j Verification

Use Neo4j when you want to verify the raw CodeGraphKB graph without trusting the local Sigma UI.

## Start Neo4j

```bash
docker compose -f docker-compose.neo4j.yml up -d
```

Neo4j Browser:

```text
http://localhost:7474
user: neo4j
password: codegraphkb
```

## Install Driver

```bash
pip install -e ".[neo4j]"
```

## Push CodeGraphKB Data

From the indexed repo:

```bash
codegraph index . --force
codegraph export neo4j --repo . --view full --clear
```

You can also push a narrower view:

```bash
codegraph export neo4j --repo . --view framework --clear
codegraph export neo4j --repo . --view calls --clear
```

## Useful Cypher Checks

Counts by node kind:

```cypher
MATCH (n:CodeGraphNode)
RETURN n.kind AS kind, count(*) AS count
ORDER BY count DESC;
```

Counts by relationship type:

```cypher
MATCH (:CodeGraphNode)-[r]->(:CodeGraphNode)
RETURN type(r) AS type, count(*) AS count
ORDER BY count DESC;
```

Find disconnected routes:

```cypher
MATCH (r:CodeGraphRoute)
OPTIONAL MATCH (r)-[rel]-()
RETURN r.id AS id, r.label AS label, count(rel) AS degree
ORDER BY degree ASC, label
LIMIT 50;
```

Inspect route edges:

```cypher
MATCH (r:CodeGraphRoute)-[rel]-(n:CodeGraphNode)
RETURN r, rel, n
LIMIT 100;
```

Inspect a suspicious symbol neighborhood:

```cypher
MATCH (n:CodeGraphNode)
WHERE n.label CONTAINS "index_repository"
OPTIONAL MATCH path = (n)-[*1..2]-(m:CodeGraphNode)
RETURN path
LIMIT 50;
```

## Reset Neo4j

The exporter clears only nodes labeled `CodeGraphNode` by default:

```cypher
MATCH (n:CodeGraphNode) DETACH DELETE n;
```
