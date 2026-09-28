"""检查新增能力、Docker 构建上下文和日志配置的结构契约。"""

import ast
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


def main() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    required = [
        root / "runtime" / "assist.py",
        root / "runtime" / "registry.py",
        root / "runtime" / "brief.py",
        root / "runtime" / "web_lookup.py",
        root / "runtime" / "browser_tool.py",
        root / "runtime" / "ingest.py",
        root / "observability" / "logging_setup.py",
        root / ".dockerignore",
    ]
    for path in required:
        assert path.is_file(), path
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8"))

    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    ignore = (root / ".dockerignore").read_text(encoding="utf-8")
    assert "playwright install" in dockerfile
    assert "markitdown" in requirements and "docling" in requirements
    assert "models/" in ignore and "logs/" in ignore
    print("[OK] project-layout")


if __name__ == "__main__":
    main()
