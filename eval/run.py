"""run.py — 在评估集上跑分

用法：
    # 干跑：只校验数据集本身，不调用模型（零成本，先确认数据集可用）
    python -m eval.run --dry-run

    # 真跑：对每个用例调用 agent
    python -m eval.run

    # 只跑某一类
    python -m eval.run --category tool

设计要点：
- **先记录基线分数再优化** —— 没有基线的"评估体系"等于没有（见 docs/2-产品规格.md 第 6 节）
- 每个用例用**独立的 session**，防止记忆互相污染（这本身就是 v1 修过的 bug）
- 分数可复现：同一份数据集、同一份代码，重复跑应当得到相近结果
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "agent-lite"))

DATASET = _HERE / "dataset.jsonl"
RESULTS_DIR = _HERE / "results"

# 评分用到的检查类型
CHECK_TYPES = {"contains", "regex", "any_of"}


def load_dataset(path: Path) -> list[dict]:
    cases = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"dataset.jsonl 第 {lineno} 行不是合法 JSON：{e}") from e
            cases.append(case)
    return cases


def validate_case(case: dict) -> list[str]:
    """校验单条用例的结构，返回问题列表（空列表 = 合法）"""
    problems = []
    for field in ("id", "category", "turns", "check"):
        if field not in case:
            problems.append(f"缺少字段 {field}")
    if not isinstance(case.get("turns"), list) or not case.get("turns"):
        problems.append("turns 必须是非空列表")
    check = case.get("check") or {}
    if check.get("type") not in CHECK_TYPES:
        problems.append(f"check.type 必须是 {sorted(CHECK_TYPES)} 之一，实际 {check.get('type')!r}")
    if "value" not in check:
        problems.append("check 缺少 value")
    return problems


def judge(reply: str, check: dict) -> bool:
    """按检查规则判定一次回复是否通过"""
    if reply is None:
        return False
    text = str(reply)
    kind = check.get("type")
    value = check.get("value")

    if kind == "contains":
        return str(value) in text
    if kind == "regex":
        return re.search(str(value), text, re.IGNORECASE) is not None
    if kind == "any_of":
        return any(str(v).lower() in text.lower() for v in value)
    return False


# 上游不可用的特征（中转站实测会间歇性 503，见 LESSONS.md）
_TRANSIENT_MARKERS = ("503", "502", "504", "暂时不可用", "稍后重试", "timeout", "Timeout", "rate limit", "429")


def _is_transient(exc: Exception) -> bool:
    msg = str(exc)
    return any(m in msg for m in _TRANSIENT_MARKERS)


async def ask_with_retry(agent_loop, user_message: str, memory, tools, waits=(0, 10, 30)):
    """带重试的提问 —— 上游断流时不至于让整条评估白跑

    评估结果必须可信：一次 503 导致的失败会被记成"用例不过"，
    那评估就变成了在测上游稳定性，而不是在测 agent。
    """
    last_exc = None
    for i, w in enumerate(waits):
        if w:
            await asyncio.sleep(w)
        try:
            return await agent_loop(
                user_message=user_message, memory=memory, tools=tools, tool_session_map=None
            )
        except Exception as e:
            last_exc = e
            if not _is_transient(e) or i == len(waits) - 1:
                raise
    raise last_exc


async def run_case(case: dict) -> dict:
    """跑单个用例：多轮依次提问，取**最后一轮**的回复判定"""
    from config import client
    from memory import HybridMemory
    from router import SYSTEM_PROMPT_BASE, build_tool_table
    from tools_local import LOCAL_TOOLS
    from agent import agent_loop

    system_prompt = SYSTEM_PROMPT_BASE.format(tool_table=build_tool_table(LOCAL_TOOLS))
    # 每个用例独立 session —— 防止用例之间记忆串味
    memory = HybridMemory(
        system_prompt=system_prompt, client=client, session_id=f"eval-{case['id']}"
    )

    replies = []
    for turn in case["turns"]:
        reply = await ask_with_retry(agent_loop, turn, memory, LOCAL_TOOLS)
        replies.append(reply)

    passed = judge(replies[-1], case["check"])
    return {
        "id": case["id"],
        "category": case["category"],
        "passed": passed,
        "turns": case["turns"],
        "check": case["check"],
        "final_reply": (replies[-1] or "")[:300],
    }


def summarize(results: list[dict]) -> dict:
    """汇总分数：整体 + 分类"""
    by_cat: dict[str, dict] = {}
    for r in results:
        c = by_cat.setdefault(r["category"], {"total": 0, "passed": 0})
        c["total"] += 1
        c["passed"] += 1 if r["passed"] else 0

    for c in by_cat.values():
        c["rate"] = round(c["passed"] / c["total"], 4) if c["total"] else 0.0

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "score": round(passed / total, 4) if total else 0.0,
        "by_category": dict(sorted(by_cat.items())),
    }


def print_report(summary: dict, results: list[dict], verbose: bool) -> None:
    print("=" * 62)
    print(f"  评估结果    {summary['passed']}/{summary['total']} 通过"
          f"    得分 {summary['score']:.1%}")
    print("=" * 62)
    print()
    print(f"  {'分类':<14}{'通过/总数':<14}{'得分':<10}")
    print(f"  {'-' * 40}")
    for cat, c in summary["by_category"].items():
        print(f"  {cat:<14}{c['passed']}/{c['total']:<12}{c['rate']:.1%}")

    failed = [r for r in results if not r["passed"]]
    if failed and verbose:
        print()
        print(f"  ---- 未通过用例（{len(failed)}）----")
        for r in failed:
            print(f"  [{r['id']}] {' / '.join(r['turns'])}")
            print(f"      检查：{r['check']['type']} = {r['check']['value']!r}")
            print(f"      实际：{r['final_reply'][:120]!r}")
    elif failed:
        print()
        print(f"  未通过：{', '.join(r['id'] for r in failed)}")
    print()


def compare_with_baseline(summary: dict, results: list[dict], baseline_path: Path) -> int:
    """与基线对比，打印变好/变坏/新增/消失的用例

    这才是评估体系存在的意义：**回答"这次改动是变好还是变坏"**。
    只跑出个数字不和历史比，等于没有评估。
    """
    try:
        with open(baseline_path, "r", encoding="utf-8") as f:
            baseline = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[跳过对比] 读不到基线 {baseline_path}：{e}")
        return 0

    base_sum = baseline.get("summary", {})
    base_results = {r["id"]: r["passed"] for r in baseline.get("results", [])}
    cur_results = {r["id"]: r["passed"] for r in results}

    print("=" * 62)
    print("  与基线对比")
    print("=" * 62)
    b_score = base_sum.get("score", 0.0)
    c_score = summary["score"]
    delta = c_score - b_score
    arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
    print(f"  基线得分 {b_score:.1%}  {arrow}  本次 {c_score:.1%}"
          f"   （{delta:+.1%}）")
    base_at = baseline.get("generated_at", "?")
    print(f"  基线时间 {base_at}")
    print()

    # 分类对比
    base_cats = base_sum.get("by_category", {})
    print(f"  {'分类':<14}{'基线':<12}{'本次':<12}{'变化'}")
    print(f"  {'-' * 46}")
    for cat, c in summary["by_category"].items():
        b = base_cats.get(cat)
        if not b:
            print(f"  {cat:<14}{'—':<12}{c['rate']:.1%}{'':<6}(基线无此分类)")
            continue
        d = c["rate"] - b["rate"]
        mark = "↑" if d > 0.001 else ("↓" if d < -0.001 else "→")
        print(f"  {cat:<14}{b['rate']:.1%}{'':<7}{c['rate']:.1%}{'':<7}{mark} {d:+.1%}")

    # 逐条对比 —— 找出"本来过、现在不过"的回归，这是最需要立刻知道的事
    regressed = [i for i, ok in cur_results.items() if not ok and base_results.get(i) is True]
    fixed = [i for i, ok in cur_results.items() if ok and base_results.get(i) is False]
    new_cases = [i for i in cur_results if i not in base_results]
    gone_cases = [i for i in base_results if i not in cur_results]

    print()
    if regressed:
        print(f"  [REGRESSION] 回归（基线过、本次不过）{len(regressed)} 条：")
        for i in regressed:
            print(f"     - {i}")
    if fixed:
        print(f"  [FIXED] 修复（基线不过、本次过）{len(fixed)} 条：")
        for i in fixed:
            print(f"     - {i}")
    if new_cases:
        print(f"  [NEW] 新增用例 {len(new_cases)} 条：{', '.join(new_cases)}")
    if gone_cases:
        print(f"  [GONE] 基线有但本次没跑 {len(gone_cases)} 条：{', '.join(gone_cases)}")
    if not any([regressed, fixed, new_cases, gone_cases]):
        print("  逐条结果与基线完全一致")

    print()
    return len(regressed)


def main() -> int:
    parser = argparse.ArgumentParser(description="在评估集上跑分")
    parser.add_argument("--dry-run", action="store_true",
                        help="只校验数据集，不调用模型（零成本）")
    parser.add_argument("--category", help="只跑某一类（tool/memory/multiturn/error/basic）")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印未通过用例的详情")
    parser.add_argument("--limit", type=int, help="最多跑几条（调试用）")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--baseline", type=Path, default=RESULTS_DIR / "baseline.json",
                        help="对比用的基线文件（默认 eval/results/baseline.json）")
    parser.add_argument("--no-compare", action="store_true", help="跳过与基线的对比")
    args = parser.parse_args()

    cases = load_dataset(args.dataset)

    # ---- 数据集自检（无论如何都先做）----
    problems = []
    seen_ids = set()
    for case in cases:
        for p in validate_case(case):
            problems.append(f"{case.get('id', '(无 id)')}: {p}")
        cid = case.get("id")
        if cid in seen_ids:
            problems.append(f"{cid}: id 重复")
        seen_ids.add(cid)

    print(f"数据集：{args.dataset}")
    print(f"用例数：{len(cases)}")
    if problems:
        print(f"\n[FAIL] 数据集有 {len(problems)} 处问题：")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("[OK] 数据集结构校验通过")

    cats: dict[str, int] = {}
    for c in cases:
        cats[c["category"]] = cats.get(c["category"], 0) + 1
    print(f"分类分布：{cats}")
    print()

    if args.dry_run:
        print("[dry-run] 未调用模型。去掉 --dry-run 可跑真实评估。")
        return 0

    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
        if not cases:
            print(f"[FAIL] 没有 category={args.category!r} 的用例")
            return 1
    if args.limit:
        cases = cases[: args.limit]

    # ⚠️ 必须先加载 .env 再检查 —— 否则在 shell 里没手动 export key 的用户
    #    会看到一个假的"未设置 API key"错误（这个 bug 真实发生过）。
    from config import client, aclient  # noqa: F401  import 触发 load_dotenv

    if not os.getenv("OPENAI_API_KEY"):
        print("[FAIL] 未设置 OPENAI_API_KEY —— 真实评估需要模型凭据")
        print("       检查 .env 是否存在且含该键；只想校验数据集就加 --dry-run")
        return 1

    print(f"开始评估 {len(cases)} 条用例……")
    print()

    async def _all():
        out = []
        for i, case in enumerate(cases, 1):
            try:
                out.append(await run_case(case))
            except Exception as e:
                out.append({
                    "id": case["id"], "category": case["category"], "passed": False,
                    "turns": case["turns"], "check": case["check"],
                    "final_reply": f"(执行异常：{type(e).__name__}: {e})",
                })
            mark = "OK  " if out[-1]["passed"] else "FAIL"
            print(f"  [{i:>2}/{len(cases)}] [{mark}] {case['id']}")
        return out

    results = asyncio.run(_all())
    summary = summarize(results)
    print()
    print_report(summary, results, args.verbose)

    # 落盘结果 —— 有了历史才能比较"改动之后是变好还是变坏"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = RESULTS_DIR / f"run-{stamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "dataset": str(args.dataset),
            "summary": summary,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"结果已保存：{out_path}")

    # 与基线对比 —— 这才是评估体系存在的意义
    regressions = 0
    if not args.no_compare:
        if args.baseline.exists():
            print()
            regressions = compare_with_baseline(summary, results, args.baseline)
        else:
            print()
            print("提示：还没有基线。建议把本次结果定为基线，之后每次改动都能对比：")
            print(f"      copy {out_path.name} baseline.json")

    print()
    if regressions:
        print(f"⚠️ 有 {regressions} 条相对基线发生回归 —— 请检查上面的红色列表。")
        return 3
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
