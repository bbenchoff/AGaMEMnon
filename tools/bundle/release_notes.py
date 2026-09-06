"""Render checked-in notes with tag-bound links for a GitHub release body."""
import argparse
import posixpath
import re
from pathlib import Path
from urllib.parse import urlsplit


def render_notes(root, tag):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("release tag must be vMAJOR.MINOR.PATCH")
    relative = "docs/RELEASE_" + tag[1:].replace(".", "_") + ".md"
    source = Path(root) / relative
    if not source.is_file():
        raise ValueError("missing release notes: " + relative)
    content = source.read_text(encoding="utf-8")

    def bind_link(match):
        label, target = match.groups()
        if urlsplit(target).scheme or target.startswith(("#", "//")):
            return match.group(0)
        path = posixpath.normpath(posixpath.join("docs", target))
        if path.startswith(("../", "/")):
            raise ValueError("release link leaves repository: " + target)
        return "[%s](https://github.com/bbenchoff/AGaMEMnon/blob/%s/%s)" % (
            label, tag, path)

    return re.sub(r"\[([^\]]+)\]\(([^\s)]+)\)", bind_link, content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.output.write_text(render_notes(root, args.tag), encoding="utf-8")


if __name__ == "__main__":
    main()
