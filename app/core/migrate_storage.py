"""Copy existing attachment files between storage backends (default: local disk -> S3).

"""
import argparse
import asyncio
import sys
from dataclasses import dataclass, field


@dataclass
class Result:
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    would_copy: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)


async def migrate(items, src, dst, *, dry_run=False, delete_source=False) -> Result:
    """items: iterable of (storage_key, expected_size_bytes)."""
    res = Result()
    for key, size in items:
        if not await src.exists(key):
            res.missing.append(key)
            continue
        if await dst.exists(key) and await dst.size(key) == size:
            res.skipped.append(key)
            copied_ok = True
        elif dry_run:
            res.would_copy.append(key)
            continue
        else:
            try:
                await dst.save(key, src.read_chunks(key))
                if await dst.size(key) != size:
                    raise ValueError("size differs after copy")
                res.copied.append(key)
                copied_ok = True
            except Exception as exc:  # keep going; report at the end
                res.failed.append(f"{key}: {exc}")
                continue
        if delete_source and copied_ok and not dry_run:
            await src.delete(key)
            res.deleted.append(key)
    return res


async def run(args) -> int:
    from sqlalchemy import select

    from app.core.database import SessionLocal, engine
    from app.core.storage import build_local, build_s3
    from app.models import Attachment

    src, dst = (build_local(), build_s3()) if args.direction == "local-to-s3" else (build_s3(), build_local())
    async with SessionLocal() as session:
        rows = (await session.execute(select(Attachment.storage_key, Attachment.size_bytes))).all()
    print(f"{len(rows)} attachment(s) in the database; {src.name} -> {dst.name}"
          + ("  [DRY RUN]" if args.dry_run else ""))
    res = await migrate(rows, src, dst, dry_run=args.dry_run, delete_source=args.delete_source)
    await engine.dispose()
    print(f"copied {len(res.copied)}, already there {len(res.skipped)}, "
          f"would copy {len(res.would_copy)}, missing at source {len(res.missing)}, "
          f"failed {len(res.failed)}, source files removed {len(res.deleted)}")
    for line in res.failed:
        print("  FAILED:", line)
    for key in res.missing:
        print("  MISSING at source:", key)
    return 1 if res.failed else 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--direction", choices=["local-to-s3", "s3-to-local"], default="local-to-s3")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--delete-source", action="store_true")
    sys.exit(asyncio.run(run(p.parse_args())))


if __name__ == "__main__":
    main()