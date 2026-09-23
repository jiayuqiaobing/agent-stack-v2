"""verify_auth.py — 任务 1.1 独立验证（不碰 tests/）

预期行为（与 test_auth.py 一致）：
- 未配置 API_KEY → 放行
- 配置了 → 无 key / 错 key / 非 Bearer → 401，对 key → 通过
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException

from auth import verify_api_key


def expect_ok(label, fn):
    try:
        fn()
    except Exception as e:
        print(f"[FAIL] {label}: {type(e).__name__}: {e}")
        return False
    print(f"[OK] {label}")
    return True


def expect_401(label, fn):
    try:
        fn()
    except HTTPException as e:
        if e.status_code == 401:
            print(f"[OK] {label}")
            return True
        print(f"[FAIL] {label}: status={e.status_code}")
        return False
    except Exception as e:
        print(f"[FAIL] {label}: {type(e).__name__}: {e}")
        return False
    print(f"[FAIL] {label}: expected 401, got pass")
    return False


def main():
    results = []

    os.environ.pop("API_KEY", None)
    results.append(expect_ok("no API_KEY allows None", lambda: verify_api_key(authorization=None)))
    results.append(expect_ok("no API_KEY allows Bearer", lambda: verify_api_key(authorization="Bearer whatever")))

    os.environ["API_KEY"] = "secret-key"
    results.append(expect_401("missing header -> 401", lambda: verify_api_key(authorization=None)))
    results.append(expect_401("wrong key -> 401", lambda: verify_api_key(authorization="Bearer wrong-key")))
    results.append(expect_401("non-bearer -> 401", lambda: verify_api_key(authorization="Basic abc")))
    results.append(expect_ok("correct key accepted", lambda: verify_api_key(authorization="Bearer secret-key")))

    os.environ.pop("API_KEY", None)

    if all(results):
        print("[OK] verify_auth all passed")
        return 0
    print("[FAIL] verify_auth failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
