#!/usr/bin/env python3
"""Restore corrupted Open WebUI config and fix null 'info' fields in tool_server connections."""
import sqlite3, json, sys, os

DB = "/data/webui.db"

CORRECT = {
    "version": 0,
    "ui": {"enable_signup": False},
    "openai": {
        "enable": True,
        "api_base_urls": ["https://api.openai.com/v1", "https://openrouter.ai/api/v1"],
        "api_keys": ["", os.environ.get("OPENROUTER_API_KEY", "")],
        "api_configs": {
            "0": {"enable": True},
            "1": {"enable": True, "tags": [], "prefix_id": "", "model_ids": [],
                  "connection_type": "external", "auth_type": "bearer"}
        }
    },
    "ollama": {
        "enable": True,
        "base_urls": ["http://localhost:11434", "http://host.docker.internal:11434"],
        "api_configs": {
            "0": {"enable": True},
            "1": {"enable": True, "tags": [], "prefix_id": "", "model_ids": [],
                  "connection_type": "external", "auth_type": "bearer", "key": ""}
        }
    },
    "direct": {"enable": False},
    "models": {"base_models_cache": False},
    "tool_server": {
        "connections": [
            {"url": "http://host.docker.internal:8001/qms", "path": "/sse", "type": "mcp",
             "auth_type": "none", "headers": {}, "key": "", "config": {}, "info": {}},
            {"url": "http://host.docker.internal:8001/rosetta", "path": "/sse", "type": "mcp",
             "auth_type": "none", "headers": {}, "key": "", "config": {}, "info": {}},
        ]
    }
}

conn = sqlite3.connect(DB)
conn.execute("UPDATE config SET data=? WHERE id=1", (json.dumps(CORRECT),))
conn.commit()

# Verify
row = conn.execute("SELECT data FROM config WHERE id=1").fetchone()
parsed = json.loads(row[0])
print("Config restored and valid.")
print("tool_server connections:", len(parsed["tool_server"]["connections"]))
conn.close()
