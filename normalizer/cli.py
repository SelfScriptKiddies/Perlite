import argparse
from pathlib import Path
from .indexer import build_metadata

def main():
    parser = argparse.ArgumentParser(
        prog="perlite_tools",
        description="Normalize an Obsidian vault for Perlite and generate metadata.json",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_norm = sub.add_parser("normalize", help="Normalize links and write metadata.json")
    p_norm.add_argument("vault_root", type=Path, help="Path to the vault root")
    p_norm.add_argument("-o", "--output", type=Path, default=None,
                        help="Output metadata.json path (defaults to <vault_root>/metadata.json)")
    p_norm.add_argument("--shortest", choices=["vault", "relative"], default="vault",
                        help="Shortest path mode for note links in text (default: vault)")
    args = parser.parse_args()

    if args.cmd == "normalize":
        root = args.vault_root.resolve()
        out = args.output.resolve() if args.output else (root / "metadata.json")
        items = build_metadata(root=root, output=out, shortest_mode=args.shortest)
        print(f"Wrote {out} with {len(items)} items")
    else:
        parser.print_help()
