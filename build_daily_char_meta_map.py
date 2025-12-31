from pathlib import Path
import json
import re
from datetime import date


def iter_md_files(root: Path):
    # 生成器
    yield from root.rglob("*.md")

def date_from_path(md_file: Path, root: Path) -> str:
    # root/daily_logs/YYYY/MM/DD.md -> "YYYY-MM-DD"
    rel = md_file.relative_to(root)
    year = rel.parts[0]
    month = rel.parts[1]
    day = md_file.stem
    return f"{year}-{month}-{day}"

def count_chars_from_text(text: str) -> int:
    # 规则：去掉所有空白字符后计数
    return sum(1 for ch in text if not ch.isspace())

# 匹配：Meta名: 51 天 +   或   Meta名: 51 天
META_LINE_RE = re.compile(
    r'^\s*(?P<label>[^:\n：]+?)\s*[:：]\s*(?P<count>\d+)\s*天\s*(?P<plus>\+)?\s*$'
)

def parse_meta_from_text(text: str) -> dict:
    """
    返回结构：
    {
      "metas": { "<label>": {"count": int, "done": bool}, ... },
      "notes": "<str>"
    }
    约定：
    - 只从第 3 行开始扫描 meta（前两行是日期、正文）
    - 遇到行内容恰好为 '---'，后面全部作为 notes
    - 只有匹配 META_LINE_RE 的行才会被当作 meta 行
    """
    lines = text.splitlines()

    # 默认空
    metas: dict[str, dict] = {}
    notes = ""

    # 从第 3 行开始：索引 2
    i = 2
    while i < len(lines):
        line = lines[i].rstrip("\n")
        if line.strip() == "---":
            # 剩下的全部当 notes（不含这一行）
            notes = "\n".join(lines[i + 1:]).strip()
            break

        m = META_LINE_RE.match(line)
        if m:
            label = m.group("label").strip()
            count = int(m.group("count"))
            done = bool(m.group("plus"))
            metas[label] = {"count": count, "done": done}

        i += 1

    return {"metas": metas, "notes": notes}

def patch_done_before_cutover(daily_meta_map: dict[str, dict], cutover_date: str) -> None:
    """
    只对 cutover_date 之前的 done 进行“增量推断补全”：
    - 仅当某 label 今天的 count 比该 label 上一次出现时更大 -> 推断 done=True
    - 若原本 done=True（显式 +）则不覆盖
    - cutover_date 及之后不动（仍只认 +）
    """
    dates = sorted(daily_meta_map.keys())
    last_count: dict[str, int] = {}

    for d in dates:
        if d >= cutover_date:
            # 之后不补了；但要更新 last_count 以便后续 label 参考也行
            for label, meta in daily_meta_map[d].get("metas", {}).items():
                last_count[label] = meta.get("count", last_count.get(label, 0))
            continue

        metas = daily_meta_map[d].get("metas", {})
        for label, meta in metas.items():
            # 显式 + 的结果保留
            if meta.get("done") is True:
                last_count[label] = meta.get("count", last_count.get(label, 0))
                continue

            c = meta.get("count")
            if c is None:
                continue

            prev = last_count.get(label)
            inferred = (prev is not None and c > prev)
            meta["done"] = bool(inferred)

            last_count[label] = c

def build_daily_maps(archive_root: Path):
    """
    一次遍历同时构建：
    - daily_char_map: {date: char_count}
    - daily_meta_map: {date: {"metas":..., "notes":...}}
    """
    daily_char_map: dict[str, int] = {}
    daily_meta_map: dict[str, dict] = {}

    for md in iter_md_files(archive_root):
        d = date_from_path(md, archive_root)
        text = md.read_text(encoding="utf-8")

        daily_char_map[d] = count_chars_from_text(text)
        daily_meta_map[d] = parse_meta_from_text(text)

    return daily_char_map, daily_meta_map

def main():
    BASE_DIR = Path(__file__).resolve().parent
    ARCHIVE_ROOT = BASE_DIR / "daily_logs"
    OUT_CHAR_FILE = BASE_DIR / "daily_char_map.json"
    OUT_META_FILE = BASE_DIR / "daily_meta_map.json"

    daily_char_map, daily_meta_map = build_daily_maps(ARCHIVE_ROOT)

    # 处理过去没有"+"的问题
    patch_done_before_cutover(daily_meta_map, cutover_date="2025-12-24")

    with open(OUT_CHAR_FILE, "w", encoding="utf-8") as f:
        json.dump(daily_char_map, f, ensure_ascii=False, indent=2)

    with open(OUT_META_FILE, "w", encoding="utf-8") as f:
        json.dump(daily_meta_map, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
