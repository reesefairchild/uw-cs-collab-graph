import json
import time
from collections import defaultdict

import requests
from tqdm import tqdm

# =========================
# CONFIG
# =========================

S2_API = "https://api.semanticscholar.org/graph/v1"
SLEEP_SECONDS = 0.8  
MAX_PAPERS_PER_AUTHOR = 60  
MIN_EDGE_WEIGHT = 2

# Semantic Scholar fields
AUTHOR_FIELDS = "name,affiliations,paperCount"
PAPER_FIELDS = "title,year,authors"

# Optional: restrict to recent papers only
MIN_YEAR = None  # set None to disable

# =========================
# HELPERS
# =========================

def read_researchers(path="researchers.txt"):
    names = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            name = line.strip()
            if name:
                names.append(name)
    return names


def s2_get(url, params=None):
    """Basic GET with simple retry."""
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            else:
                # print(r.status_code, r.text)
                time.sleep(1.5)
        except Exception:
            time.sleep(1.5)
    return None


def find_author_id_by_name(name):
    """
    Semantic Scholar author search:
    /author/search?query=...&limit=...
    We'll take the top result.
    """
    url = f"{S2_API}/author/search"
    params = {
        "query": name,
        "limit": 1,
        "fields": AUTHOR_FIELDS
    }
    data = s2_get(url, params=params)
    if not data:
        for i in range(3):
            time.sleep(3)
            data = s2_get(url, params=params)
            if data:
                break
    if not data or "data" not in data or len(data["data"]) == 0:
        return None

    top = data["data"][0]
    return top.get("authorId"), top


def get_author_papers(author_id, limit=MAX_PAPERS_PER_AUTHOR):
    """
    /author/{authorId}/papers?fields=...&limit=...
    """
    url = f"{S2_API}/author/{author_id}/papers"
    params = {
        "fields": PAPER_FIELDS,
        "limit": limit
    }
    data = s2_get(url, params=params)
    if not data or "data" not in data:
        return []
    return data["data"]


# =========================
# MAIN PIPELINE
# =========================

def main():
    researchers = read_researchers("researchers.txt")
    print(f"Loaded {len(researchers)} researchers.")

    # 1) Map researcher name -> authorId
    uw_author_ids = {}
    uw_author_meta = {}

    print("\nFinding Semantic Scholar author IDs...")
    for name in tqdm(researchers):
        author_id, meta = find_author_id_by_name(name)
        time.sleep(SLEEP_SECONDS)

        if not author_id:
            print(f"[WARN] Could not find authorId for: {name}")
            continue

        uw_author_ids[name] = author_id
        uw_author_meta[name] = meta

    print(f"\nResolved {len(uw_author_ids)} / {len(researchers)} names.")

    # 2) Build coauthorship counts
    # We'll count edges between UW researcher and ALL their coauthors
    edge_weights = defaultdict(int)

    # We'll also store node metadata for coauthors we encounter
    node_meta = {}

    # Add UW nodes
    for name, author_id in uw_author_ids.items():
        node_meta[author_id] = {
            "id": author_id,
            "name": name,
            "type": "uw",
            "affiliations": uw_author_meta.get(name, {}).get("affiliations", []),
            "paperCount": uw_author_meta.get(name, {}).get("paperCount", None),
        }

    print("\nFetching papers and building edges...")
    for name, author_id in tqdm(uw_author_ids.items()):
        papers = get_author_papers(author_id)
        time.sleep(SLEEP_SECONDS)

        for p in papers:
            year = p.get("year", None)
            if MIN_YEAR is not None and year is not None and year < MIN_YEAR:
                continue

            authors = p.get("authors", [])
            # authors are like: [{"authorId": "...", "name": "..."}]
            for a in authors:
                a_id = a.get("authorId")
                a_name = a.get("name")
                if not a_id or not a_name:
                    continue

                # store metadata for this coauthor
                if a_id not in node_meta:
                    node_meta[a_id] = {
                        "id": a_id,
                        "name": a_name,
                        "type": "coauthor"
                    }

                # edge between UW researcher and this author
                if a_id != author_id:
                    # undirected edge key
                    u = str(author_id)
                    v = str(a_id)
                    if u > v:
                        u, v = v, u
                    edge_weights[(u, v)] += 1

    # 3) Build graph JSON
    # Filter edges by min weight
    edges = []
    for (u, v), w in edge_weights.items():
        if w >= MIN_EDGE_WEIGHT:
            edges.append({"source": u, "target": v, "weight": w})

    # Keep only nodes that appear in at least 1 edge
    used_nodes = set()
    for e in edges:
        used_nodes.add(str(e["source"]))
        used_nodes.add(str(e["target"]))

    nodes = []
    for node_id, meta in node_meta.items():
        if str(node_id) in used_nodes:
            nodes.append(meta)

    # Add degree (collab count) for sizing in visualization
    degree = defaultdict(int)
    for e in edges:
        degree[str(e["source"])] += 1
        degree[str(e["target"])] += 1

    for n in nodes:
        n["degree"] = degree[str(n["id"])]

    graph = {"nodes": nodes, "links": edges}

    out_path = "../web/graph.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Wrote graph to: {out_path}")
    print(f"Nodes: {len(nodes)}")
    print(f"Edges: {len(edges)}")


if __name__ == "__main__":
    main()