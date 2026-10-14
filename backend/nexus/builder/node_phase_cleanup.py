"""V3 removes only the copied baseline through nofollow directory descriptors."""

from __future__ import annotations


def cleanup_script() -> str:
    return """import os, stat
flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
remaining = 100000
def remove_entries(directory):
    global remaining
    for name in os.listdir(directory):
        remaining -= 1
        if remaining < 0:
            raise ValueError("Baseline cleanup entry bound exceeded")
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, flags, dir_fd=directory)
            try:
                remove_entries(child)
            finally:
                os.close(child)
            os.rmdir(name, dir_fd=directory)
        else:
            os.unlink(name, dir_fd=directory)
scratch = os.open("/scratch", flags)
try:
    work = os.open("work", flags, dir_fd=scratch)
    try:
        baseline = os.open("baseline", flags, dir_fd=work)
        try:
            remove_entries(baseline)
        finally:
            os.close(baseline)
        os.rmdir("baseline", dir_fd=work)
    finally:
        os.close(work)
finally:
    os.close(scratch)
"""
