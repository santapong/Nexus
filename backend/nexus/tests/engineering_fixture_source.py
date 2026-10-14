"""Generated harmless JS quantity parser and genuine Git patch; no StockFlow source execution."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from nexus.builder.contracts import RepositoryPin

CASES = (
    "quantity.valid.v1",
    "quantity.nonnumeric.v1",
    "quantity.fractional.v1",
    "quantity.trailing.v1",
    "quantity.infinity.v1",
    "quantity.unsafe.v1",
    "quantity.zero.v1",
)
BEFORE = "exports.quantity=(s)=>{const n=Number.parseInt(s,10);return n<=0?null:n};\n"
AFTER = (
    "exports.quantity=(s)=>{s=s.trim();const n=Number(s);"
    "return /^\\d+$/.test(s)&&Number.isSafeInteger(n)&&n>0?n:null};\n"
)
VERIFY = """const fs=require('fs'),assert=require('assert');
const {quantity}=require('./quantity.cjs');
const post=process.env.NEXUS_OUTPUT_DIR.endsWith('/post');
const cases=[['quantity.valid.v1','3',3],['quantity.nonnumeric.v1','bad',null],
['quantity.fractional.v1','1.5',null],['quantity.trailing.v1','2junk',null],
['quantity.infinity.v1','Infinity',null],['quantity.unsafe.v1','9007199254740993',null],
['quantity.zero.v1','0',null]];
const actual=post?cases:[cases[0],cases[6]];
for(const [key,input,expected] of actual)assert.strictEqual(quantity(input),expected,key);
fs.mkdirSync(process.env.NEXUS_OUTPUT_DIR+'/checks',{recursive:true});
fs.writeFileSync(process.env.NEXUS_OUTPUT_DIR+'/checks/behavior.json',JSON.stringify({
schema_version:'nexus.engineering.behavior.v1',cases:actual.map(([case_id])=>({case_id,status:'pass'}))}));
"""


def generated_repository(root: Path) -> tuple[Path, RepositoryPin, bytes]:
    repository = root / "harmless-engineering-repository"
    repository.mkdir(mode=0o700)
    (repository / "quantity.cjs").write_text(BEFORE)
    (repository / "verify.cjs").write_text(VERIFY)

    def git(*args: str) -> bytes:
        return subprocess.check_output(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(repository),
                *args,
            ],
            stderr=subprocess.DEVNULL,
        )

    git("init", "-q")
    git("add", ".")
    git(
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "harmless quantity source",
    )
    pin = RepositoryPin(
        repository_symbol="fixture.engineering.v1",
        commit=git("rev-parse", "HEAD").decode().strip(),
        tree=git("rev-parse", "HEAD^{tree}").decode().strip(),
        archive_sha256=hashlib.sha256(git("archive", "--format=tar", "HEAD")).hexdigest(),
    )
    (repository / "quantity.cjs").write_text(AFTER)
    patch = git("diff", "--no-ext-diff", "--no-textconv", "--", "quantity.cjs")
    (repository / "quantity.cjs").write_text(BEFORE)
    return repository, pin, patch
