from __future__ import annotations
import csv, json, sqlite3, statistics
from pathlib import Path
from typing import Any
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join

def data_read_csv(path: str, delimiter: str = ",", runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    with target.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        rows = list(reader)
    return {"path": str(target), "columns": reader.fieldnames or [], "rows": rows, "count": len(rows)}

def data_read_json(path: str, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    data = json.loads(target.read_text(encoding="utf-8"))
    return {"path": str(target), "data": data}

def _rows_from_file(runtime, path: str) -> list[dict[str, Any]]:
    if path.lower().endswith(".csv"):
        return data_read_csv(path, runtime=runtime)["rows"]
    data = data_read_json(path, runtime=runtime)["data"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # First list value or singleton dict.
        for v in data.values():
            if isinstance(v, list):
                return v
        return [data]
    return [{"value": data}]

def data_clean(path: str, output: str | None = None, drop_empty_rows: bool = True, trim_strings: bool = True, runtime=None) -> dict[str, Any]:
    rows = _rows_from_file(runtime, path)
    cleaned = []
    for row in rows:
        if not isinstance(row, dict):
            row = {"value": row}
        new = {}
        for k, v in row.items():
            nk = str(k).strip() if trim_strings else str(k)
            if isinstance(v, str) and trim_strings:
                v = v.strip()
            new[nk] = v
        if drop_empty_rows and all(v in ("", None) for v in new.values()):
            continue
        cleaned.append(new)
    if output:
        out = safe_join(runtime.workspace, output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
        out_path = str(out)
    else:
        out_path = None
    return {"rows": cleaned, "count": len(cleaned), "output": out_path}

def data_profile(path: str, runtime=None) -> dict[str, Any]:
    rows = _rows_from_file(runtime, path)
    columns = sorted({str(k) for r in rows if isinstance(r, dict) for k in r.keys()})
    profile = {"row_count": len(rows), "columns": {}}
    for col in columns:
        values = [r.get(col) for r in rows if isinstance(r, dict)]
        missing = sum(1 for v in values if v in ("", None))
        nums = []
        for v in values:
            try:
                if v not in ("", None):
                    nums.append(float(v))
            except Exception:
                pass
        item = {"missing": missing, "non_missing": len(values) - missing}
        if nums:
            item.update({"min": min(nums), "max": max(nums), "mean": sum(nums)/len(nums), "count_numeric": len(nums)})
            if len(nums) > 1:
                item["stdev"] = statistics.stdev(nums)
        profile["columns"][col] = item
    return profile

def _query_rows(rows: list[dict[str, Any]], sql: str) -> list[dict[str, Any]]:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    try:
        cols = sorted({str(k) for r in rows if isinstance(r, dict) for k in r.keys()}) or ["value"]
        con.execute("CREATE TABLE data (" + ", ".join([f'"{c}" TEXT' for c in cols]) + ")")
        for r in rows:
            if not isinstance(r, dict):
                r = {"value": r}
            con.execute("INSERT INTO data (" + ", ".join(f'"{c}"' for c in cols) + ") VALUES (" + ", ".join("?" for _ in cols) + ")", [r.get(c) for c in cols])
        cur = con.execute(sql)
        return [dict(row) for row in cur.fetchall()]
    finally:
        con.close()

def data_query(path: str, sql: str, runtime=None) -> dict[str, Any]:
    rows = _rows_from_file(runtime, path)
    return {"rows": _query_rows(rows, sql)}

def chart_create(path: str, x: str, y: str, output: str = "chart.png", chart_type: str = "line", runtime=None) -> dict[str, Any]:
    try:
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("chart.create requires matplotlib: pip install matplotlib") from exc
    rows = _rows_from_file(runtime, path)
    xs = [r.get(x) for r in rows]
    ys = []
    for r in rows:
        try:
            ys.append(float(r.get(y)))
        except Exception:
            ys.append(None)
    target = safe_join(runtime.workspace, output)
    target.parent.mkdir(parents=True, exist_ok=True)
    plt.figure()
    if chart_type == "bar":
        plt.bar(xs, ys)
    elif chart_type == "scatter":
        plt.scatter(xs, ys)
    else:
        plt.plot(xs, ys)
    plt.xlabel(x); plt.ylabel(y); plt.title(f"{y} by {x}")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig(target)
    plt.close()
    return {"path": str(target), "bytes": target.stat().st_size, "chart_type": chart_type}

def sqlite_create(path: str, schema: str | None = None, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target)
    try:
        if schema:
            con.executescript(schema)
        con.commit()
    finally:
        con.close()
    return {"path": str(target), "created": True}

def sqlite_query(path: str, sql: str, params: list[Any] | None = None, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    con = sqlite3.connect(target)
    con.row_factory = sqlite3.Row
    try:
        cur = con.execute(sql, params or [])
        if sql.strip().lower().startswith(("select", "pragma", "with")):
            rows = [dict(row) for row in cur.fetchall()]
        else:
            con.commit()
            rows = []
        return {"path": str(target), "rows": rows, "rowcount": cur.rowcount}
    finally:
        con.close()

def sql_query(connection: str, sql: str, params: list[Any] | None = None, runtime=None) -> dict[str, Any]:
    # For this standalone version, connection is a workspace SQLite path.
    return sqlite_query(connection, sql, params=params, runtime=runtime)

TOOLS = [
    ToolSpec("data.read_csv", "Read a CSV file.", object_schema({"path": {"type": "string"}, "delimiter": {"type": "string", "default": ","}}, ["path"]), data_read_csv),
    ToolSpec("data.read_json", "Read a JSON file.", object_schema({"path": {"type": "string"}}, ["path"]), data_read_json),
    ToolSpec("data.clean", "Clean rows from CSV/JSON and optionally write JSON output.", object_schema({"path": {"type": "string"}, "output": {"type": ["string", "null"], "default": None}, "drop_empty_rows": {"type": "boolean", "default": True}, "trim_strings": {"type": "boolean", "default": True}}, ["path"]), data_clean),
    ToolSpec("data.profile", "Create a simple data profile.", object_schema({"path": {"type": "string"}}, ["path"]), data_profile),
    ToolSpec("data.query", "Run SQL against CSV/JSON rows using table name data.", object_schema({"path": {"type": "string"}, "sql": {"type": "string"}}, ["path", "sql"]), data_query),
    ToolSpec("chart.create", "Create a chart image from CSV/JSON data.", object_schema({"path": {"type": "string"}, "x": {"type": "string"}, "y": {"type": "string"}, "output": {"type": "string", "default": "chart.png"}, "chart_type": {"type": "string", "default": "line"}}, ["path", "x", "y"]), chart_create),
    ToolSpec("sql.query", "Run SQL against a SQLite database path.", object_schema({"connection": {"type": "string"}, "sql": {"type": "string"}, "params": {"type": ["array", "null"], "default": None}}, ["connection", "sql"]), sql_query),
    ToolSpec("sqlite.create", "Create a SQLite database with optional schema.", object_schema({"path": {"type": "string"}, "schema": {"type": ["string", "null"], "default": None}}, ["path"]), sqlite_create),
    ToolSpec("sqlite.query", "Run a SQLite query.", object_schema({"path": {"type": "string"}, "sql": {"type": "string"}, "params": {"type": ["array", "null"], "default": None}}, ["path", "sql"]), sqlite_query),
]
