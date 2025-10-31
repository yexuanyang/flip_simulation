#!/usr/bin/env python3
import os
import re
import sys
import struct
import mmap
import subprocess
from collections import deque
import random
import time


PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") 
PAGEMAP_ENTRY_BYTES = struct.calcsize("Q")
PFN_MASK = ((1 << 55) - 1)



def find_pids_by_name(comm_name):
    """
    Match the process name precisely against /proc/[pid]/comm
    """
    output = subprocess.check_output(["ps", "-eo", "pid,comm"], encoding="utf-8")
    lines = output.splitlines()[1:]
    pids = []
    for line in lines:
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid, comm = parts
        if comm == comm_name:
            pids.append(int(pid))
    return sorted(pids)


def find_pids_by_cmdline_substring(keyword):
    """
    Fuzzy matching of keywords in command lines, such as python3 test.py
    """
    current_pid = os.getpid()
    script_name = os.path.basename(__file__)
    output = subprocess.check_output(["ps", "-eo", "pid,args"], encoding="utf-8")
    lines = output.splitlines()[1:]
    pids = []
    for line in lines:
        if keyword in line:
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            pid_str, cmdline = parts
            try:
                pid = int(pid_str)
                # Excludes itself and scripts with the same name
                if pid == current_pid or script_name in cmdline:
                    continue
                pids.append(pid)
            except:
                continue
    return sorted(pids)


def find_all_descendants(pids):
    """
    Starting from the main PID list, recursively search all child processes.
    """
    output = subprocess.check_output(["ps", "-eo", "pid,ppid"], encoding="utf-8")
    child_map = {}
    for line in output.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        pid, ppid = int(parts[0]), int(parts[1])
        child_map.setdefault(ppid, []).append(pid)

    all_pids = set(pids)
    queue = deque(pids)
    while queue:
        current = queue.popleft()
        for child in child_map.get(current, []):
            if child not in all_pids:
                all_pids.add(child)
                queue.append(child)
    return sorted(all_pids)


def parse_maps(pid):
    ranges = []
    try:
        with open(f"/proc/{pid}/maps") as f:
            for line in f:
                m = re.match(r"([0-9a-f]+)-([0-9a-f]+)\s+(\S+)", line)
                if not m:
                    continue
                start = int(m.group(1), 16)
                end = int(m.group(2), 16)
                perms = m.group(3)
                if "r" in perms:  # 可读段才读取
                    ranges.append((start, end))
    except Exception as e:
        print(f" Failed to parse maps for PID {pid}: {e}")
    return ranges


def parse_rw_anon_maps(pid):
    """只提取匿名 rw-p 段（无文件名）"""
    ranges = []
    try:
        with open(f"/proc/{pid}/maps") as f:
            for line in f:
                m = re.match(
                    r"([0-9a-f]+)-([0-9a-f]+)\s+([rwxps-]+)\s+[0-9a-f]+\s+[0-9a-f:]+\s+\d+\s*(.*)",
                    line,
                )
                if not m:
                    continue
                start, end = int(m.group(1), 16), int(m.group(2), 16)
                perms = m.group(3)
                pathname = m.group(4)
                if (
                    "r" in perms
                    and "w" in perms
                    and "p" in perms
                    and pathname.strip() == ""
                ):
                    ranges.append((start, end))
    except Exception as e:
        print(f" Failed to parse maps for PID {pid}: {e}")
    return ranges


def read_pagemap_entries(pid, vaddrs):
    pagemap_path = f"/proc/{pid}/pagemap"
    results = []
    try:
        with open(pagemap_path, "rb") as f:
            for vaddr in vaddrs:
                index = (vaddr // PAGE_SIZE) * PAGEMAP_ENTRY_BYTES
                f.seek(index)
                data = f.read(8)
                if len(data) != 8:
                    continue
                entry = struct.unpack("Q", data)[0]
                present = (entry >> 63) & 1
                pfn = entry & PFN_MASK
                if present and pfn != 0:
                    phys_addr = pfn * PAGE_SIZE
                    results.append((vaddr, phys_addr))
    except Exception as e:
        print(f" Failed to read pagemap for PID {pid}: {e}")
    return results


def get_phys_for_pid(pid):
    vaddrs = []
    for start, end in parse_maps(pid):
        for addr in range(start, end, PAGE_SIZE):
            vaddrs.append(addr)

    entries = read_pagemap_entries(pid, vaddrs)
    return entries


def merge_ranges(ranges):
    """
    Merge consecutive physical address page ranges
    """
    if not ranges:
        return []
    sorted_ranges = sorted(ranges)
    merged = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        last_start, last_end = merged[-1]
        if start == last_end:
            merged[-1] = (last_start, end)
        else:
            merged.append((start, end))
    return merged


if __name__ == "__main__":
    """
    Options: 
            -f <app_execute_command>  Execute programs that require multiple commands or complex parameters (such as Python scripts).
                Format:-f "command arg1 arg2 ..."
            
            Execute a single simple command (such as a browser, a program without parameters).
                Format:program_name
    """

    if os.geteuid() != 0:
        print(" Please run as root.")
        sys.exit(1)

    if len(sys.argv) < 2:
        print(
            f"Usage:\n  sudo {sys.argv[0]} <comm>\n  sudo {sys.argv[0]} -f <keyword_in_cmdline>"
        )
        sys.exit(1)

    if len(sys.argv) == 2:
        keyword = sys.argv[1]
        base_pids = find_pids_by_name(keyword)
    elif len(sys.argv) == 3 and sys.argv[1] == "-f":
        keyword = sys.argv[2]
        base_pids = find_pids_by_cmdline_substring(keyword)
    else:
        print(
            f" Invalid arguments.\nUsage:\n  sudo {sys.argv[0]} <comm>\n  sudo {sys.argv[0]} -f <keyword_in_cmdline>"
        )
        sys.exit(1)

    if not base_pids:
        print(f" No process found matching: {keyword}")
        sys.exit(1)
    all_pids = find_all_descendants(base_pids)

    all_phys = set()
    for pid in all_pids:
        entries = get_phys_for_pid(pid)
        for vaddr, paddr in entries:
            all_phys.add((paddr, paddr + PAGE_SIZE))

    merged_ranges = merge_ranges(all_phys)
    for start, end in merged_ranges:
        print(f"  0x{start:016x}-0x{end:016x}")
