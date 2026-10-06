#!/usr/bin/env python3
"""按章节清单生成完整小说及阅读目录；仅使用 Python 标准库。"""

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "章节清单.json"
INDEX = ROOT / "章节目录.md"


def is_inside(path, directory):
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def required_text(item, key):
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"章节清单缺少有效字段：{key}")
    return value.strip()


def read_chapters():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    title = required_text(data, "title")
    output = required_text(data, "output")
    if not isinstance(data.get("parts"), list) or not data["parts"]:
        raise ValueError("章节清单的 parts 必须是非空列表")

    chapter_root = (ROOT / "正文").resolve()
    paths, labels, part_labels = set(), set(), set()
    parts = []
    epilogue_seen = False
    next_chapter = 1
    for part in data["parts"]:
        part_label = required_text(part, "label")
        part_title = required_text(part, "title")
        if part_label in part_labels:
            raise ValueError(f"重复的部：{part_label}")
        part_labels.add(part_label)
        entries = part.get("chapters")
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"{part_label}没有章节")
        chapters = []
        for entry in entries:
            label = required_text(entry, "label")
            chapter_title = required_text(entry, "title")
            relative = Path(required_text(entry, "file"))
            if relative.is_absolute():
                raise ValueError(f"章节路径须相对于仓库根目录：{relative}")
            path = (ROOT / relative).resolve()
            if not is_inside(path, chapter_root) or path.suffix.lower() != ".md":
                raise ValueError(f"章节必须位于正文目录内且为 .md：{relative}")
            if path in paths or label in labels:
                raise ValueError(f"章节重复：{label} / {relative}")
            if epilogue_seen:
                raise ValueError("尾声必须位于全书最后")
            kind = entry.get("kind", "chapter")
            if kind not in ("chapter", "epilogue"):
                raise ValueError(f"未知章节种类：{kind}")
            expected_label = f"第{next_chapter}章" if kind == "chapter" else "尾声"
            if label != expected_label:
                raise ValueError(f"章节编号不连续：应为{expected_label}，实际为{label}")
            if kind == "chapter":
                next_chapter += 1
            epilogue_seen = kind == "epilogue"
            if not path.is_file():
                raise ValueError(f"缺少章节文件：{relative}")

            text = path.read_text(encoding="utf-8-sig").strip()
            lines = text.splitlines()
            if not lines or not lines[0].startswith("# "):
                raise ValueError(f"章节首行须为 Markdown 标题：{relative}")
            if lines[0] != f"# {label} {chapter_title}":
                raise ValueError(f"章节标题与清单不一致：{relative}")
            body = "\n".join(lines[1:]).strip()
            if not body:
                raise ValueError(f"章节正文为空：{relative}")
            paths.add(path)
            labels.add(label)
            chapters.append({
                "label": label,
                "title": chapter_title,
                "path": path,
                "kind": kind,
                "body": body,
                "hanzi": len(re.findall(r"[\u4e00-\u9fff]", body)),
            })
        parts.append({"label": part_label, "title": part_title, "chapters": chapters})

    actual = {path.resolve() for path in chapter_root.rglob("*.md") if path.is_file()}
    extra = actual - paths
    if extra:
        names = "、".join(str(path.relative_to(ROOT)) for path in sorted(extra))
        raise ValueError(f"正文中有未列入章节清单的文件：{names}")
    return title, output, parts


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            prefix=f".{path.name}.", suffix=".tmp",
            dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def relative_link(path):
    return Path(os.path.relpath(path, ROOT)).as_posix()


def render(title, parts, output):
    entries = [chapter for part in parts for chapter in part["chapters"]]
    chapter_count = sum(chapter["kind"] == "chapter" for chapter in entries)
    epilogue_count = sum(chapter["kind"] == "epilogue" for chapter in entries)
    total = sum(chapter["hanzi"] for chapter in entries)
    book = [f"# {title}", ""]
    index = [
        f"# 《{title}》章节目录", "",
        f"正文{chapter_count}章＋尾声{epilogue_count}篇，共{len(entries)}个独立文件；正文{total:,}汉字。",
        "",
        f"- [完整小说](<{relative_link(output)}>)",
        "- [合并脚本](<工具/合稿.py>)",
        "- [章节清单](<章节清单.json>)",
        "",
        "每个独立文件计一章，正文连续编号，尾声不编号。正文修改后重新运行脚本，即可更新本目录和完整小说。",
        "",
        "| 章节 | 独立源文件 | 正文汉字 |",
        "|---|---|---:|",
    ]
    for part in parts:
        book.extend([f"## {part['label']}　{part['title']}", ""])
        for chapter in part["chapters"]:
            heading = f"{chapter['label']}　{chapter['title']}"
            book.extend([f"### {heading}", "", chapter["body"], "", "---", ""])
            index.append(
                f"| {heading} | "
                f"[{chapter['path'].name}](<{relative_link(chapter['path'])}>) | {chapter['hanzi']:,} |"
            )
    while book and book[-1] in ("", "---"):
        book.pop()
    return "\n".join(book) + "\n", "\n".join(index) + "\n", (
        chapter_count, epilogue_count, len(entries), total
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="核对清单、正文和生成文件是否同步，不写文件")
    parser.add_argument("--output", type=Path, help="另存完整稿；路径相对于仓库根目录，必须在仓库内")
    args = parser.parse_args()
    try:
        title, default_output, parts = read_chapters()
        requested = args.output if args.output is not None else Path(default_output)
        output = (ROOT / requested).resolve()
        if not is_inside(output, ROOT):
            raise ValueError("完整稿的输出文件须位于仓库内")
        if output.suffix.lower() != ".md":
            raise ValueError("完整稿的输出文件须以 .md 结尾")
        if (
            any(
                is_inside(output, (ROOT / name).resolve())
                for name in ("正文", "设定", "编辑记录", "工具", "archive", ".git")
            )
            or output in {
                INDEX.resolve(), (ROOT / "README.md").resolve(), (ROOT / "AGENTS.md").resolve()
            }
        ):
            raise ValueError("输出路径不能覆盖章节、设定、目录或版本说明")
        book, index, counts = render(title, parts, output)
        if args.check:
            stale = [
                relative_link(path)
                for path, expected in ((output, book), (INDEX, index))
                if not path.is_file() or path.read_text(encoding="utf-8") != expected
            ]
            if stale:
                raise ValueError(
                    "生成文件未同步：" + "、".join(stale)
                    + "；请先运行 python3 工具/合稿.py"
                )
        else:
            atomic_write(output, book)
            atomic_write(INDEX, index)
        chapters, epilogues, files, hanzi = counts
        print(f"检查通过：{chapters}章正文＋{epilogues}篇尾声，{files}个文件，{hanzi:,}汉字。")
        if not args.check:
            print(f"完整稿：{output}")
            print(f"章节目录：{INDEX}")
        return 0
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(f"合并失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
