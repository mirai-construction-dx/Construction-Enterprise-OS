"""MCPツール定義ハッシュ（Core 規約）
対象キー: name, title, description, inputSchema, outputSchema, annotations, x-mirai
正規化: RFC 8785（JCS） -> SHA-256（小文字16進）
"""
import hashlib
import json
import sys

import rfc8785

HASHED_KEYS = ("name", "title", "description", "inputSchema", "outputSchema", "annotations", "x-mirai")


def tool_definition_sha256(tool: dict) -> str:
    subset = {k: tool[k] for k in HASHED_KEYS if k in tool}
    return hashlib.sha256(rfc8785.dumps(subset)).hexdigest()


if __name__ == "__main__":
    for path in sys.argv[1:]:
        doc = json.load(open(path, encoding="utf-8"))
        for t in doc["tools"]:
            print(doc["server_id"], t["name"], tool_definition_sha256(t))
