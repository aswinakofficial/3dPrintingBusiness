#!/usr/bin/env python3
"""
Delete ACI container groups in terminal state older than N days.

Containers in 'Succeeded'/'Failed'/'Stopped' states don't bill, but they
clutter the resource group and consume name slots. Run this periodically
(cron, GitHub Actions, or just before a busy iteration session) to keep the
RG tidy.

Defaults to a dry run -- pass --apply to actually delete.

Usage:
    python scripts/cleanup_old_jobs.py                  # dry run, default 7 days
    python scripts/cleanup_old_jobs.py --age-days 1     # 24h+
    python scripts/cleanup_old_jobs.py --apply          # actually delete
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.mgmt.containerinstance import ContainerInstanceManagementClient

# Use the same logger as run_job.py for consistent output format.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.logger import get_logger, setup_logger  # noqa: E402

logger = get_logger()

TERMINAL_STATES = {"Succeeded", "Failed", "Stopped", "Terminated"}


def cleanup_old_jobs(
    *,
    resource_group: str,
    subscription_id: str,
    age_days: int,
    apply: bool,
) -> int:
    """Delete terminal container groups older than `age_days`. Returns count
    deleted (or that would be deleted in dry-run mode)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=age_days)
    credential = DefaultAzureCredential()
    client = ContainerInstanceManagementClient(credential, subscription_id)

    deleted = 0
    for group in client.container_groups.list_by_resource_group(resource_group):
        # Need detailed view to read instance state and provisioning timestamp.
        full = client.container_groups.get(resource_group, group.name)

        # Best-effort timestamp: ACI doesn't expose creation time directly, so
        # we use the first container's start_time when available, else skip.
        try:
            state = full.containers[0].instance_view.current_state
        except (AttributeError, IndexError):
            logger.warning(f"{group.name}: could not read state, skipping")
            continue

        if state.state not in TERMINAL_STATES:
            continue

        finish_time = getattr(state, "finish_time", None) or getattr(
            state, "start_time", None
        )
        if finish_time is None or finish_time > cutoff:
            continue

        action = "Would delete" if not apply else "Deleting"
        logger.info(f"{action}: {group.name} (state={state.state}, finished={finish_time})")
        if apply:
            try:
                client.container_groups.begin_delete(resource_group, group.name).wait()
                deleted += 1
            except Exception as e:
                logger.warning(f"Delete failed for {group.name}: {e}")
        else:
            deleted += 1

    return deleted


def main() -> int:
    setup_logger(log_dir="./logs", level="INFO")

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--resource-group",
        default=os.getenv("AZURE_RESOURCE_GROUP", "rg-3dfigurine-lab-dev-eastus"),
        help="Resource group to scan (default: env AZURE_RESOURCE_GROUP)",
    )
    p.add_argument(
        "--subscription",
        default=os.getenv("AZURE_SUBSCRIPTION_ID"),
        help="Azure subscription ID (default: env AZURE_SUBSCRIPTION_ID)",
    )
    p.add_argument(
        "--age-days",
        type=int,
        default=7,
        help="Delete terminal container groups older than this many days (default: 7)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete. Without this flag, prints what would be deleted.",
    )
    args = p.parse_args()

    if not args.subscription:
        print(
            "Error: --subscription not provided and AZURE_SUBSCRIPTION_ID unset.",
            file=sys.stderr,
        )
        return 2

    count = cleanup_old_jobs(
        resource_group=args.resource_group,
        subscription_id=args.subscription,
        age_days=args.age_days,
        apply=args.apply,
    )
    verb = "Deleted" if args.apply else "Would delete"
    logger.info(f"{verb} {count} terminal container group(s) older than {args.age_days}d.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
