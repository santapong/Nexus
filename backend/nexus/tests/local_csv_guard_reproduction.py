"""Reduced exact quantity guard only; synthetic strings, no repository mount/module/job."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from nexus.builder.process import engine_environment, limited_stream
from nexus.tests.builder_node_support import IMAGE
from nexus.tests.local_stockflow_packet import write_private

ROOT = Path("/mnt/data/nexus-implementation-evidence-2026-10-14/native-builder")
SNIPPET = """const fs=require('fs');
const raw=['bad','1.5','2junk','Infinity','9007199254740993','3','0','-1',''];
const cases=raw.map(text=>{const qty=Number.parseInt(text??'0',10);
return {text,qty,is_nan:Number.isNaN(qty),safe_integer:Number.isSafeInteger(qty),
accepted:!(!'SKU' || qty<=0 || 10000n<=0n)};});
const kernel=Object.fromEntries(['memory.max','cpu.max','pids.max'].map(name=>
[name,fs.readFileSync('/sys/fs/cgroup/'+name,'utf8').trim()]));
process.stdout.write(JSON.stringify({cases,kernel}));
"""


async def reproduce() -> None:
    probe_id = uuid4()
    name = "nexus-csv-guard-" + probe_id.hex
    argv = (
        "/usr/bin/podman",
        "--remote=false",
        "run",
        "--rm",
        "--name",
        name,
        "--label",
        f"nexus.local-probe={probe_id}",
        "--pull=never",
        "--network=none",
        "--http-proxy=false",
        "--no-hosts",
        "--no-hostname",
        "--passwd=false",
        "--no-healthcheck",
        "--read-only",
        "--read-only-tmpfs=false",
        "--image-volume=ignore",
        "--log-driver=none",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pid=private",
        "--ipc=private",
        "--uts=private",
        "--cgroupns=private",
        "--cpus=2",
        "--memory=67108864",
        "--memory-swap=67108864",
        "--pids-limit=32",
        "--timeout=30",
        "--entrypoint=/usr/local/bin/node",
        IMAGE,
        "-e",
        SNIPPET,
    )
    process = await asyncio.create_subprocess_exec(
        *argv,
        env=engine_environment(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None and process.stderr is not None
    async with asyncio.timeout(35):
        stdout, stderr = await asyncio.gather(
            limited_stream(process.stdout, 16384), limited_stream(process.stderr, 16384)
        )
        code = await process.wait()
    receipt = {
        "scope": "authorized reduced JS guard reproduction; synthetic strings, no mounts",
        "probe_id": str(probe_id),
        "argv": argv,
        "snippet_sha256": hashlib.sha256(SNIPPET.encode()).hexdigest(),
        "exit_code": code,
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
        "private_module_execution": False,
        "repository_mounts": 0,
        "new_company_actions": 0,
        "sdk_calls": 0,
        "paid_calls": 0,
        "patch_claim": False,
    }
    await asyncio.to_thread(
        write_private,
        ROOT / "csv-quantity-reduced-guard.json",
        json.dumps(receipt, indent=2).encode(),
    )
    if code != 0:
        raise ValueError("Reduced guard probe did not complete; retain failure")


if __name__ == "__main__":
    asyncio.run(reproduce())
