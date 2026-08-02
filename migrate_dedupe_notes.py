"""제목이 겹치는 노트를 정리한다: 사실상 같은 것은 접고, 다른 문서는 개명한다.

관례대로 **백업(zip) → dry-run → --execute** 순으로 동작한다. 기본은 dry-run 이라
아무것도 바꾸지 않고 계획만 보여준다.

왜 단순 '중복 삭제'가 아닌가:
- 한 제목 아래 중복과 별개 문서가 섞여 있다. 그룹 전체를 하나로 접으면 실제 자료를 잃는다
  (예: 견적서 4개 = 119,298자 통짜 서류 1개 + 거의 같은 내역서 3개).
  그래서 그룹 안에서 다시 본문 유사도로 묶는다.
- 노트가 `[[위키링크]]` 로 참조된다. 지우거나 이름을 바꾸면 링크가 조용히 깨지므로
  참조하는 쪽 본문도 같이 고친다.
"""

import argparse
import json
import re
import shutil
import zipfile
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import mcp_server

VAULT = mcp_server.VAULT
SUFFIX = re.compile(r"-(\d+)$")
LINK = re.compile(r"\[\[([^\]|#]+)([^\]]*)\]\]")
# 이 이상 닮았으면 '재추출 차이'로 보고 하나로 접는다. 0.98 은 실측으로 정한 값이다
# (0.98 이상 그룹은 글자 몇 개 차이, 그 아래는 개정판·다른 문서가 섞여 있었다).
FOLD_AT = 0.98
# 출처 파일이 같을 때 쓰는 완화된 기준. 같은 파일에서 나왔는데 이만큼 닮았다면 개정판이
# 아니라 중복 처리다(짧은 노트일수록 사소한 추출 차이가 비율을 크게 깎는다).
SAME_SOURCE_FOLD_AT = 0.90
PLAN_FILE = Path("_dedupe_plan.json")
# 출처 파일명 앞머리의 정리 번호(05_, 13., 1-1a_ 등)는 제목에 넣어도 의미가 없다.
LEAD_NUM = re.compile(r"^[\d\-]+[a-z]?[._\s]+")
RAW_HEADING = re.compile(r"^##\s*원문\s*$", re.M)


def _body(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            raw = raw[end + 4 :]
    return re.sub(r"\s+", " ", raw).strip()


def _raw_text(path: Path) -> str:
    """'## 원문' 이후만 뽑아 _body() 와 같은 방식으로 공백을 정규화한다. 헤딩이 없으면
    빈 문자열을 돌려준다(호출부가 _body() 전체로 대체한다).

    출처가 같은 두 노트를 비교할 때 '## 요약' 까지 넣으면 안 된다 — 요약은 분류를 돌릴
    때마다 새로 쓰이는 산출물이라, 같은 문서를 두 번 분류해도 문장이 달라진다. 그걸 포함해
    비교하면 '같은 문서인가'가 아니라 '분류기가 이번엔 얼마나 다르게 요약했는가'를 재는
    꼴이 된다."""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            raw = raw[end + 4 :]
    m = RAW_HEADING.search(raw)
    if not m:
        return ""
    return re.sub(r"\s+", " ", raw[m.end() :]).strip()


def _same_document(a: Path, b: Path, bodies: dict[Path, str]) -> bool:
    """두 노트가 사실상 같은 문서인가.

    유사도만 쓰면 짧은 노트에서 헛돈다 — 385자짜리에서 글자 몇 개만 달라도 비율이 크게
    떨어진다. 그래서 **출처 파일이 같으면** 기준을 낮춘다. 같은 파일에서 나온 거의 같은
    노트는 개정판일 수 없고, 추출이 두 번 돈 결과다.

    출처가 같을 때는 본문 전체가 아니라 '## 원문' 절만 비교한다. 요약은 분류기가 매번
    새로 생성하는 산출물이라 같은 문서를 두 번 돌려도 달라지고, 그 노이즈가 노트가
    짧을수록(요약이 본문에서 차지하는 비중이 클수록) 비율을 더 깎는다 — 결국 문서가
    같은지가 아니라 분류기가 얼마나 다르게 썼는지를 재게 된다. 원문만 보면 이 노이즈가
    빠져서 SAME_SOURCE_FOLD_AT(0.90) 이 진짜 기준이 된다."""
    ratio = SequenceMatcher(None, bodies[a], bodies[b]).ratio()
    if ratio >= FOLD_AT:
        return True
    src_a = mcp_server._frontmatter(a).get("source", "")
    src_b = mcp_server._frontmatter(b).get("source", "")
    if not (bool(src_a) and src_a == src_b):
        return False
    raw_a = _raw_text(a) or bodies[a]
    raw_b = _raw_text(b) or bodies[b]
    return SequenceMatcher(None, raw_a, raw_b).ratio() >= SAME_SOURCE_FOLD_AT


def _clusters(paths: list[Path], bodies: dict[Path, str]) -> list[list[Path]]:
    """본문 유사도로 묶는다. 같은 묶음 = 사실상 같은 문서."""
    out: list[list[Path]] = []
    for p in paths:
        for c in out:
            if _same_document(p, c[0], bodies):
                c.append(p)
                break
        else:
            out.append([p])
    return out


def _norm_ident(s: str) -> str:
    """비교용 정규화: 공백/밑줄/하이픈 제거(classifier/classify.py 의 동명 함수와 같은 발상.
    의존을 만들지 않으려고 그대로 가져오지 않고 여기 따로 둔다)."""
    return re.sub(r"[\s_\-]", "", s or "")


def _category_matches_source(path: Path) -> bool:
    """노트의 category 가 출처 파일명 안에 등장하는가(공백/_/- 는 무시하고 비교)."""
    fm = mcp_server._frontmatter(path)
    category, source = fm.get("category", ""), fm.get("source", "")
    if not category or not source:
        return False
    return _norm_ident(category) in _norm_ident(source)


def _keeper(cluster: list[Path], bodies: dict[Path, str], linked: set[str]) -> Path:
    """묶음에서 남길 노트. 링크가 걸린 것 > 출처 파일명에 category 가 들어있는 것 >
    본문이 긴 것 > 이름에 -N 이 없는 것 순.

    링크를 우선하는 이유: 남기는 쪽을 링크 대상과 맞추면 고칠 링크가 줄고,
    Obsidian 그래프에서 기존 연결이 그대로 유지된다.

    두 번째 기준(category)을 넣은 이유: 같은 문서를 두 번 분류했는데 category 가
    서로 갈렸다면, 원본 파일명이 더 믿을 만한 증거다. 실제 사례: '골든구스 코리아
    성수 하우스 임차의향서.pdf' 가 한 번은 `임차의향서`, 한 번은 `계약서`로 분류됐고,
    본문 길이 기준만 쓰면 틀린 쪽(계약서)이 남는다."""
    return max(
        cluster,
        key=lambda p: (
            p.stem in linked,
            _category_matches_source(p),
            len(bodies[p]),
            not SUFFIX.search(p.stem),
        ),
    )


def _disambiguator(path: Path) -> str:
    """개명 시 붙일 짧은 구분어를 출처 파일명에서 만든다."""
    source = mcp_server._frontmatter(path).get("source", "")
    if not source:
        return "사본"
    stem = LEAD_NUM.sub("", Path(source).stem).strip(" _-")
    # 대괄호는 [[위키링크]] 파싱을 흔들고, 괄호는 제목 규칙의 괄호와 섞여 짝이 어긋난다.
    # 파일명에 못 쓰는 문자도 함께 걷어낸다.
    stem = re.sub(r'[\[\]()/\\:*?"<>|]', " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" _-")
    return stem[:24].strip(" _-") or Path(source).suffix.lstrip(".")


def _unique_disambiguators(keepers: list[Path]) -> dict[Path, str]:
    """묶음 대표들에게 '서로 다른' 구분어를 준다.

    잘라 쓴 구분어가 겹치면(예: 같은 문서의 .pdf/.hwp 판) 새 이름이 충돌해 개명이
    실패하거나 서로 덮어쓴다. 겹치면 확장자를, 그래도 겹치면 번호를 덧붙인다."""
    base = {p: _disambiguator(p) for p in keepers}
    counts: dict[str, int] = defaultdict(int)
    for value in base.values():
        counts[value] += 1

    out: dict[Path, str] = {}
    used: set[str] = set()
    for p in keepers:
        value = base[p]
        if counts[value] > 1:
            ext = Path(mcp_server._frontmatter(p).get("source", "")).suffix.lstrip(".")
            if ext:
                value = f"{value} {ext}"
        candidate, n = value, 1
        while candidate in used:
            n += 1
            candidate = f"{value} {n}"
        used.add(candidate)
        out[p] = candidate
    return out


def _with_mark(stem: str, mark: str) -> str:
    """구분어를 제목 규칙에 맞게 넣는다: 'YYYY-MM-DD 유형 - 상대방 (부가, 상태)'.

    괄호를 새로 덧붙이지 않고 기존 괄호 안에 항목으로 넣어야 규칙이 유지된다."""
    if stem.endswith(")"):
        return f"{stem[:-1]}, {mark})"
    return f"{stem} ({mark})"


def _incoming_links() -> dict[str, list[Path]]:
    """노트 제목 -> 그것을 [[링크]] 로 가리키는 노트들."""
    refs: dict[str, list[Path]] = defaultdict(list)
    for p in mcp_server._notes():
        for m in LINK.finditer(p.read_text(encoding="utf-8", errors="ignore")):
            refs[m.group(1).strip().removesuffix(".md")].append(p)
    return refs


def _fold(
    paths: list[Path], bodies: dict[Path, str], linked: set[str]
) -> tuple[list[list[Path]], list[Path], list[dict], set[Path]]:
    """묶음(그룹) 안에서 클러스터링 -> 대표(keeper) 선정 -> 삭제 후보 생성까지.

    제목 그룹핑과 출처 그룹핑이 이 로직을 그대로 공유한다. `protected` 에는 실제로
    경쟁(접힘)이 있었던 대표만 담는다 — 경쟁 없이 혼자 남은 노트까지 보호 대상으로
    치면, 다른 쪽 그룹핑이 찾아낸 진짜 중복을 못 지우게 막아버릴 수 있다."""
    clusters = _clusters(paths, bodies)
    keepers = [_keeper(c, bodies, linked) for c in clusters]
    deletes: list[dict] = []
    protected: set[Path] = set()
    for cluster, keep in zip(clusters, keepers):
        for p in cluster:
            if p != keep:
                deletes.append(
                    {"path": str(p), "stem": p.stem, "merged_into": keep.stem,
                     "chars": len(bodies[p])}
                )
                protected.add(keep)
    return clusters, keepers, deletes, protected


def build_plan() -> dict:
    notes = mcp_server._notes()
    refs = _incoming_links()
    linked = set(refs)

    title_groups: dict[str, list[Path]] = defaultdict(list)
    source_groups: dict[str, list[Path]] = defaultdict(list)
    for p in notes:
        title_groups[SUFFIX.sub("", p.stem)].append(p)
        source = mcp_server._frontmatter(p).get("source", "")
        if source:
            source_groups[source].append(p)

    bodies: dict[Path, str] = {}

    def cache_bodies(paths: list[Path]) -> None:
        for p in paths:
            if p not in bodies:
                bodies[p] = _body(p)

    raw_deletes: list[dict] = []
    renames: list[dict] = []
    protected: set[Path] = set()

    # 제목이 같은 그룹: 접기 + (묶음이 둘 이상, 즉 서로 다른 문서가 제목을 공유 중이면) 개명.
    for name, paths in sorted(title_groups.items()):
        if len(paths) < 2:
            continue
        cache_bodies(paths)
        clusters, keepers, deletes, kept = _fold(paths, bodies, linked)
        raw_deletes.extend(deletes)
        protected |= kept
        if len(clusters) > 1:
            marks = _unique_disambiguators(keepers)
            for keep in keepers:
                new_stem = _with_mark(name, marks[keep])
                if new_stem != keep.stem:
                    renames.append(
                        {"path": str(keep), "stem": keep.stem, "new_stem": new_stem,
                         "chars": len(bodies[keep])}
                    )

    # 출처가 같은 그룹: 같은 원본이 두 번 처리돼 제목이 갈린 경우를 접는다(제목
    # 그룹핑은 이걸 못 잡는다). 여기서는 개명하지 않는다 — 모인 노트들은 이미 서로
    # 다른 제목이라 구분할 필요가 없다(예: 유사도가 낮은 주간운동리뷰 쌍은 클러스터가
    # 둘로 갈라져 접히지 않고 그대로 둘 다 남는다).
    for source, paths in sorted(source_groups.items()):
        if len(paths) < 2:
            continue
        cache_bodies(paths)
        _, _, deletes, kept = _fold(paths, bodies, linked)
        raw_deletes.extend(deletes)
        protected |= kept

    # 두 그룹핑을 합친다. 규칙: (1) 어느 쪽에서든 실제로 경쟁에서 이긴 대표는 다른 쪽이
    # 지우려 해도 지우지 않는다. (2) 같은 경로가 두 번 삭제 후보에 오르면 경로 자체와
    # merged_into 값만으로 하나를 고른다(어느 그룹핑을 먼저 돌렸는지에 기대지 않으므로
    # title/source 순서를 바꿔도 결과가 같다).
    best: dict[str, dict] = {}
    for d in raw_deletes:
        if Path(d["path"]) in protected:
            continue
        prev = best.get(d["path"])
        if prev is None or d["merged_into"] < prev["merged_into"]:
            best[d["path"]] = d
    deletes = sorted(best.values(), key=lambda d: d["path"])

    best_r: dict[str, dict] = {}
    for r in renames:
        prev = best_r.get(r["path"])
        if prev is None or r["new_stem"] < prev["new_stem"]:
            best_r[r["path"]] = r
    renames = sorted(best_r.values(), key=lambda r: r["path"])

    # 링크 갱신: 삭제된 노트는 살아남은 노트로, 개명된 노트는 새 이름으로 돌린다.
    remap = {d["stem"]: d["merged_into"] for d in deletes}
    remap.update({r["stem"]: r["new_stem"] for r in renames})
    # 삭제 대상이 개명도 되는 경우(삭제 -> 유지본 -> 새 이름)까지 따라간다.
    for old, new in list(remap.items()):
        seen = {old}
        while new in remap and new not in seen:
            seen.add(new)
            new = remap[new]
        remap[old] = new

    link_edits = []
    for target, sources in refs.items():
        if target in remap and remap[target] != target:
            for src in sources:
                link_edits.append(
                    {"path": str(src), "from": target, "to": remap[target]}
                )

    return {
        "created": datetime.now().isoformat(timespec="seconds"),
        "vault": str(VAULT),
        "deletes": deletes,
        "renames": renames,
        "link_edits": link_edits,
        "broken_links": [
            {"in": p.stem, "target": t}
            for t, srcs in refs.items()
            if t not in {n.stem for n in notes}
            for p in srcs
        ],
    }


def print_plan(plan: dict) -> None:
    print(f"볼트: {plan['vault']}\n")
    print(f"=== 접기(삭제) {len(plan['deletes'])}개 ===")
    for d in plan["deletes"]:
        print(f"  - {d['stem'][:70]}  ({d['chars']:,}자)")
        print(f"      -> 유지: {d['merged_into'][:66]}")
    print(f"\n=== 개명 {len(plan['renames'])}개 ===")
    for r in plan["renames"]:
        print(f"  - {r['stem'][:70]}")
        print(f"      -> {r['new_stem'][:70]}")
    print(f"\n=== 링크 갱신 {len(plan['link_edits'])}곳 ===")
    for e in plan["link_edits"]:
        print(f"  {Path(e['path']).stem[:44]}: [[{e['from'][:40]}]] -> [[{e['to'][:40]}]]")
    if plan["broken_links"]:
        print(f"\n=== 이미 깨져 있던 링크 {len(plan['broken_links'])}개(이번에 손대지 않음) ===")
        for b in plan["broken_links"]:
            print(f"  {b['in'][:44]} -> [[{b['target'][:44]}]]")


def backup() -> Path:
    dest = Path(f"vault_backup_{datetime.now():%Y%m%d_%H%M%S}.zip")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in VAULT.rglob("*.md"):
            z.write(p, p.relative_to(VAULT))
    return dest


def apply_plan(plan: dict) -> None:
    # 링크부터 고친다. 파일 이름이 바뀌기 전에 옛 이름으로 찾아야 하기 때문이다.
    edits: dict[Path, list[dict]] = defaultdict(list)
    for e in plan["link_edits"]:
        edits[Path(e["path"])].append(e)
    for path, items in edits.items():
        text = path.read_text(encoding="utf-8")
        for e in items:
            text = text.replace(f"[[{e['from']}]]", f"[[{e['to']}]]")
            text = text.replace(f"[[{e['from']}.md]]", f"[[{e['to']}.md]]")
        path.write_text(text, encoding="utf-8")
    print(f"링크 갱신: {len(plan['link_edits'])}곳")

    for d in plan["deletes"]:
        Path(d["path"]).unlink(missing_ok=True)
    print(f"삭제: {len(plan['deletes'])}개")

    for r in plan["renames"]:
        src = Path(r["path"])
        if src.exists():
            src.rename(src.with_name(r["new_stem"] + src.suffix))
    print(f"개명: {len(plan['renames'])}개")


def main() -> None:
    ap = argparse.ArgumentParser(description="제목이 겹치는 노트 정리(기본 dry-run)")
    ap.add_argument("--execute", action="store_true", help="실제로 적용한다(백업 후)")
    args = ap.parse_args()

    plan = build_plan()
    print_plan(plan)
    PLAN_FILE.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n계획을 {PLAN_FILE} 에 저장했습니다.")

    if not args.execute:
        print("dry-run 입니다. 적용하려면 --execute 를 붙이세요.")
        return

    zip_path = backup()
    print(f"\n백업: {zip_path} ({zip_path.stat().st_size / 2**20:.1f}MB)")
    apply_plan(plan)
    print("\n완료. 인덱스를 갱신하세요: uv run python ingest_vault.py")


if __name__ == "__main__":
    main()
