
import math
import os
import platform
import subprocess
from typing import Dict
import sys

import wandarr
from wandarr.media import MediaInfo
from wandarr.template import Template


def filter_threshold(template: Template, in_path: str, out_path: str):
    if template.threshold() > 0:
        orig_size = os.path.getsize(in_path)
        new_size = os.path.getsize(out_path)
        return is_exceeded_threshold(template.threshold(), orig_size, new_size)
    return True


def is_exceeded_threshold(pct_threshold: int, orig_size: int, new_size: int) -> bool:
    pct_savings = 100 - math.floor((new_size * 100) / orig_size)
    if pct_savings < pct_threshold:
        return False
    return True


def files_from_file(queue_path) -> list:
    if queue_path == '-':
        with sys.stdin as qf:
            _files = [fn.rstrip() for fn in qf.readlines()]
            return _files
    else:   
        if not os.path.exists(queue_path):
            print('File of files not found - nothing to do')
            return []
        with open(queue_path, 'r', encoding="utf8") as qf:
            _files = [fn.rstrip() for fn in qf.readlines()]
            return _files


def get_local_os_type():
    return {'Windows': 'win10', 'Linux': 'linux', 'Darwin': 'macos'}.get(platform.system(), 'unknown')


def calculate_progress(info: MediaInfo, stats: Dict) -> (int, int):
    # pct done calculation only works if video duration >= 1 minute
    if info.runtime > 0:
        pct_done = int((stats['time'] / info.runtime) * 100)
    else:
        pct_done = 0

    # extrapolate current compression %

    filesize = info.filesize_mb * 1024000
    pct_source = int(filesize * (pct_done / 100.0))
    if pct_source <= 0:
        return 0, 0
    pct_dest = int((stats['size'] / pct_source) * 100)
    pct_comp = 100 - pct_dest

    return pct_done, pct_comp


def run(cmd):
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False) as p:
        output = p.communicate()[0].decode('utf-8')
        return p.returncode, output


def dump_stats(completed):

    if wandarr.DRY_RUN:
        return

    paths = [p for p, _ in completed]
    max_width = len(max(paths, key=len))
    print("-" * (max_width + 9))
    for path, elapsed in completed:
        pathname = path.rjust(max_width)
        _min = int(elapsed / 60)
        _sec = int(elapsed % 60)
        print(f"{pathname}  ({_min:3}m {_sec:2}s)")
    print()
