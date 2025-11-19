import argparse
import os
import random
import re
import sys
import time
import uuid

import gdb

# add path to sys.path to find modules in the same dir.
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from buildcmd import BuildCmd
from logger import init_logger
from parser import parse_args_safely
from qemu_utils import *


@BuildCmd
def listram(args):
    """List all RAM ranges allocated by QEMU."""

    print("QEMU RAM list:")
    memory = mtree()["memory"]
    for start, end in memory.ram_ranges():
        print("  RAM allocated from 0x%x to 0x%x" % (start, end))
    print("Sampled index: 0x%x" % memory.random_address())


@BuildCmd
def listreg(args):
    """List all CPU registers available in QEMU."""

    print("QEMU CPU register list:")
    register = Registers()
    lr = register.list_registers()
    maxlen = max(len(r.name) for r, nb in lr)
    print("  REG:", "Name".rjust(maxlen), "->", "Bytes")
    for register, num_bytes in lr:
        print("  REG:", register.name.rjust(maxlen), "->", num_bytes)


@BuildCmd
def stop_delayed(args):
    """Stop the QEMU instance after a delay of the input nano-seconds."""

    parser = argparse.ArgumentParser(
        description="Stop the QEMU instance after a delay", prog="stop_delayed"
    )
    parser.add_argument(
        "--ns", type=float, required=True, help="Nanoseconds to delay before stopping"
    )

    parsed = parse_args_safely(parser, args)
    if parsed is None:
        return

    step_ns(parsed.ns)


@BuildCmd
def inject(args):
    """Inject a bitflip at an address."""

    parser = argparse.ArgumentParser(
        description="Inject a bitflip at an address", prog="inject"
    )
    parser.add_argument(
        "--address",
        required=True,
        help="Address to inject bitflip (if not specified, randomly selected)",
    )
    parser.add_argument(
        "--bytewidth",
        required=True,
        type=int,
        help="Byte width (default: 4 if address specified, 1 if random)",
    )
    parser.add_argument(
        "--bit", required=True, type=int, help="Bit index within the integer to flip"
    )

    parsed = parse_args_safely(parser, args)
    if parsed is None:
        return

    if parsed.address:
        # Support argument like "inject --address 0x1234+0x11 --bytewidth 4 --bit 3"
        try:
            address = int(gdb.parse_and_eval(parsed.address))
        except Exception as e:
            print("Error parsing address: %s" % str(e))
            return
        bytewidth = parsed.bytewidth if parsed.bytewidth is not None else 4
        if bytewidth < 1 or address < 0:
            print("invalid bytewidth or address")
            return
    else:
        address = sample_address()
        bytewidth = 1

    bit = parsed.bit

    inject_bitflip(address, bytewidth, bit)


@BuildCmd
def inject_reg(args):
    """Inject a bitflip into a register.
    usage: inject_reg [--register <register name>] [--bit <bit index>]
    if no register specified, will be randomly selected,
    a pattern involving wildcards can be specified if desired
    """

    parser = argparse.ArgumentParser(
        description="Inject a bitflip into a register",
        prog="inject_reg",
    )
    parser.add_argument(
        "--register",
        required=True,
        help="Register name (supports wildcards, if not specified, randomly selected)",
    )
    parser.add_argument("--bit", required=True, type=int, help="Bit index to flip")

    parsed = parse_args_safely(parser, args)
    if parsed is None:
        return

    inject_reg_internal(parsed.register, parsed.bit)


# @BuildCmd
# def task_restart(args):
#     """Inject a UDF instruction to force a task restart."""
#     if args.strip():
#         print("usage: task_restart")
#         return

#     inject_instant_restart()


@BuildCmd
def loginject(args):
    """Log the injection of a bitflip"""

    parser = argparse.ArgumentParser(
        description="Log the injection of a bitflip to a CSV file",
        prog="loginject",
    )
    parser.add_argument(
        "--filename", required=True, help="CSV filename to log bitflip injections"
    )

    parsed = parse_args_safely(parser, args)
    if parsed is None:
        return

    init_logger(parsed.filename)


@BuildCmd
def autoinject(args):
    """Automatically inject fault into the VM accroding to the provided inject type.
    Cause `total_fault_number` faults with a random cycle between `min_interval` and `max_interval`,
    fault type is `fault_type`

    Usage: `autoinject --total-fault-number <num> --min-interval <time> --max-interval <time> --fault-type <type>`

    Supported types:
    1. ram: inject fault in RAM
    2. reg: inject fault in Registers"""

    parser = argparse.ArgumentParser(
        description="Automatically inject faults into the VM",
        prog="autoinject",
    )
    parser.add_argument(
        "--total-fault-number",
        type=int,
        required=True,
        help="Total number of faults to inject",
    )
    parser.add_argument(
        "--min-interval",
        required=True,
        help="Minimum interval between injections (with unit: ns, us, ms, s, m)",
    )
    parser.add_argument(
        "--max-interval",
        required=True,
        help="Maximum interval between injections (with unit: ns, us, ms, s, m)",
    )
    parser.add_argument(
        "--fault-type",
        choices=["ram", "reg"],
        required=True,
        help="Type of fault to inject",
    )

    parsed = parse_args_safely(parser, args)
    if parsed is None:
        return

    try:
        times = getattr(parsed, "total_fault_number")
        assert times >= 1, "fatal: times < 1"
        mint = parse_time(getattr(parsed, "min_interval"))
        maxt = parse_time(getattr(parsed, "max_interval"))
        assert 0 < mint <= maxt, "fatal: min_interval > max_interval"
        ftype = getattr(parsed, "fault_type")
    except (ValueError, AssertionError) as e:
        print("Error: %s" % str(e))
        return

    stime = time.time()
    autoinject_inner(times, mint, maxt, ftype)
    etime = time.time()
    duration = etime - stime
    print("Total injection duration: %.3f s" % duration)


@BuildCmd
def inject_range(args):
    """Inject bitflips at addresses within specified ranges."""

    args = args.strip().split(" ")
    if len(args) < 3:
        print(
            "usage: inject_range <bytewidth> <mode> <range1> [<range2> ...] [<num_errors>]"
        )
        print("Each range should be specified as start-end (e.g., 0x1000-0x1FFF)")
        print(
            "Mode should be 'sequential' or 'random'. If 'random', specify the number of errors to inject."
        )
        return

    bytewidth = int(args[0])
    mode = args[1]
    if bytewidth < 1:
        print("invalid bytewidth")
        return

    ranges = []
    for arg in args[2:]:
        if "-" in arg:
            try:
                start, end = map(lambda x: int(x, 16), arg.split("-"))
                if start >= end:
                    raise ValueError
                ranges.append((start, end))
            except ValueError:
                print(f"invalid range: {arg}")
                return
        else:
            num_errors = int(arg)

    if mode == "sequential":
        for start, end in ranges:
            for address in range(start, end + 1, bytewidth):
                inject_bitflip(address, bytewidth)
    elif mode == "random":
        if "num_errors" not in locals():
            print(
                "usage: inject_range <bytewidth> random <range1> [<range2> ...] <num_errors>"
            )
            return
        all_addresses = []
        for start, end in ranges:
            all_addresses.extend(range(start, end + 1, bytewidth))
        if num_errors > len(all_addresses):
            print("Number of errors exceeds the number of available addresses.")
            return
        random_addresses = random.sample(all_addresses, num_errors)
        for address in random_addresses:
            inject_bitflip(address, bytewidth)
    else:
        print("Invalid mode. Use 'sequential' or 'random'.")


@BuildCmd
def snapinject(args):
    """Record the current VM state, then automatically inject faults according to the user-provided fault count, fault location, and fault interval.
    After the faults are injected, wait for a while and then revert to the previous VM state, delete the tmp checkpoint.
    Usage: snapinject --total-fault-number <num> --min-interval <time> --max-interval <time> --fault-type <type> --fault-location <location> --bit-index <bit> --observe-time <time> [--snapshot-tag <tag>] [--register-category <category>] [--bytewidth <width>] [--no-snapshot]
    Example:
        snapinject --total-fault-number 10 --min-interval 100ms --max-interval 200ms --fault-type ram --fault-location 0x00500000 --bit-index 1 --observe-time 10s --bytewidth 4
        snapinject --total-fault-number 10 --min-interval 100ms --max-interval 100ms --fault-type reg --fault-location pc --bit-index 3 --observe-time 10s --snapshot-tag my_snapshot
        snapinject --total-fault-number 10 --min-interval 100ms --max-interval 100ms --fault-type reg --register-category general --bit-index 3 --observe-time 10s --snapshot-tag my_snapshot
        snapinject --total-fault-number 10 --min-interval 100ms --max-interval 200ms --fault-type ram --fault-location 0x00500000 --bit-index 1 --observe-time 10s --bytewidth 4 --no-snapshot

    Supported time units: default is ns. Time format: 10s, 244ms and etc.
    1. ns: nanosecond
    2. us: microsecond
    3. ms: millisecond
    4. s: second
    5. m: minute
    Supported fault type and fault location:
    1. ram, address: inject fault in RAM, location is "address"
    2. reg, regname: inject fault in Registers, target is "regname"
    Supported register categories (for fault-type reg):
    1. general: includes x0-x30, pc, sp, cpsr, fpsr, fpcr (AArch64 general-purpose registers)
    2. control: includes all other registers except general-purpose registers
    """
    parser = argparse.ArgumentParser(
        description="Custom snapshot-based fault injection with specific location",
        prog="snapinject",
    )
    parser.add_argument(
        "--total-fault-number",
        type=int,
        required=True,
        help="Total number of faults to inject",
    )
    parser.add_argument(
        "--min-interval",
        required=True,
        help="Minimum interval between injections (with unit: ns, us, ms, s, m)",
    )
    parser.add_argument(
        "--max-interval",
        required=True,
        help="Maximum interval between injections (with unit: ns, us, ms, s, m)",
    )
    parser.add_argument(
        "--fault-type",
        choices=["ram", "reg"],
        required=True,
        help="Type of fault to inject",
    )
    parser.add_argument(
        "--fault-location",
        required=False,
        help="Fault location (address for RAM, register name for REG)",
    )
    parser.add_argument(
        "--bit-index", type=int, required=False, help="Bit index to flip"
    )
    parser.add_argument(
        "--bytewidth",
        type=int,
        default=1,
        help="Byte width for RAM fault injection (default: 1)",
    )
    parser.add_argument(
        "--observe-time",
        required=True,
        help="Time to observe after injection (with unit: ns, us, ms, s, m)",
    )
    parser.add_argument(
        "--snapshot-tag",
        help="Optional snapshot tag (if not provided, creates temporary snapshot)",
    )
    parser.add_argument(
        "--serial-socket",
        required=True,
        help="The socket file used to send string to qemu serial",
    )
    parser.add_argument(
        "--register-category",
        choices=["general", "control"],
        help="Register category for fault injection when fault-type is 'reg'. 'general' includes x0-x30, pc, sp, cpsr, fpsr, fpcr. 'control' includes all other registers. If not specified, all registers are considered.",
    )
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="If specified, do not create/load/restore snapshots. Just inject faults and observe.",
    )

    parsed = parse_args_safely(parser, args)
    if parsed is None:
        return

    try:
        times = getattr(parsed, "total_fault_number")
        assert times >= 1, "fatal: times < 1"
        mint = parse_time(getattr(parsed, "min_interval"))
        maxt = parse_time(getattr(parsed, "max_interval"))
        assert 0 <= mint <= maxt, "fatal: min_interval > max_interval"
        ftype = getattr(parsed, "fault_type")
        obtime = parse_time(getattr(parsed, "observe_time"))
    except (ValueError, AssertionError) as e:
        print("Error: %s" % str(e))
        return

    tmpname = uuid.uuid4()
    location = getattr(parsed, "fault_location")
    bit_index = getattr(parsed, "bit_index")
    register_category = getattr(parsed, "register_category")
    bytewidth = getattr(parsed, "bytewidth")
    no_snapshot = getattr(parsed, "no_snapshot")

    if (location is None and bit_index is not None) and (
        location is not None and bit_index is None
    ):
        print(
            "Error: --bit-index and --fault-location must be both specified or both omitted."
        )
        return

    # 检查寄存器类别参数的有效性
    if ftype == "reg" and register_category is not None and location is not None:
        print(
            "Error: --register-category and --fault-location cannot be used together when fault-type is 'reg'. Use either specific register name or register category."
        )
        return

    # 验证 bytewidth 参数的有效性
    if bytewidth < 1:
        print("Error: --bytewidth must be >= 1")
        return

    # 处理快照逻辑
    snapname = None
    if not no_snapshot:
        snapname = (
            getattr(parsed, "snapshot_tag")
            if getattr(parsed, "snapshot_tag")
            else tmpname
        )
        if snapname == tmpname:
            qemu_hmp("savevm %s" % snapname)
            print("Create a tmp checkpoint %s" % snapname)
        else:
            qemu_hmp("loadvm %s" % snapname)
            qemu_hmp("cont")
            print("Load checkpoint %s" % snapname)
    else:
        print("Snapshot disabled, injecting faults without snapshot.")

    stime = time.time()
    if location is None and bit_index is None and register_category is None:
        # 没有指定具体位置、位索引或寄存器类别，使用原有的随机注入
        autoinject_inner(times, mint, maxt, ftype)
    else:
        for _ in range(times):
            step_ns(random.randint(mint, maxt))
            if ftype == "ram":
                try:
                    address = int(location, 16)
                    inject_bitflip(
                        address, bytewidth, bit_index
                    )  # Use specified byte width and bit_index
                except ValueError as e:
                    print("Error parsing RAM address: %s" % str(e))
                    return
            elif ftype == "reg":
                if register_category is not None:
                    # 使用寄存器类别注入
                    inject_reg_by_category(register_category, bit_index)
                elif location is not None:
                    # 使用指定寄存器名称注入
                    inject_register_bitflip(location, bit_index)
                else:
                    # 只指定了 bit_index，随机选择寄存器
                    inject_reg_internal(None, bit_index)
    etime = time.time()
    duration = etime - stime
    print("Total injection duration: %.3f s" % duration)

    print("Observing VM %s" % getattr(parsed, "observe_time"))
    step_ns(obtime)
    print("time up.")

    if not no_snapshot and snapname:
        if snapname == tmpname:
            # Revert to the previous VM state
            qemu_hmp("loadvm %s" % snapname)
            print("Back to checkpoint %s finished." % snapname)
            # Del this tmp VM checkpoint
            qemu_hmp("delvm %s" % tmpname)
            print("Delete tmp VM checkpoint")

    # Send a ret to qemu serial, make sure prompt is back
    send_to_qemu_serial("\r", parsed.serial_socket)


def parse_address_ranges_file(path):
    """
    Parse an address range file of the following format and return a list of all injectable addresses:
        0x0000000002800000-0x0000000002a00000
        0x0000000003400000-0x0000000003800000
    """
    address_list = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or "-" not in line:
                continue
            try:
                start_str, end_str = line.split("-")
                start = int(start_str, 16)
                end = int(end_str, 16)
                address_list.extend(range(start, end, 1))  # 每 1 字节为单位注入
            except Exception as e:
                print(f"Invalid line in range file: {line} ({e})")
    return address_list


@BuildCmd
def loop(args):
    """Loop a action for provide times
    Usage: loop --times <num> --command <cmd> [--command-args <args>...]
    """
    parser = argparse.ArgumentParser(
        description="Loop an action for the specified number of times",
        prog="loop",
    )
    parser.add_argument(
        "--times", type=int, required=True, help="Number of times to repeat the command"
    )
    parser.add_argument("--command", required=True, help="Command to execute")
    parser.add_argument("--command-args", nargs="*", help="Arguments for the command")

    parsed = parse_args_safely(parser, args)
    if parsed is None:
        return

    times = parsed.times
    # Reconstruct the full command with arguments
    actions = parsed.command
    if getattr(parsed, "command_args"):
        actions += " " + " ".join(getattr(parsed, "command_args"))

    for _ in range(times):
        gdb.execute(actions)


@BuildCmd
def appinject(args):
    # TODO: Use argparse to parse the param here
    """Inject bitflips at addresses loaded from a file.

        Need to be used with find_phys_ranges.py
    Usage:
        appinject <count> <range_file>
            <count>: number of random bitflip injections to perform
            <range_file>: path to the file that contains address ranges

    """

    parser = argparse.ArgumentParser(
        description="Inject bitflips at address loaded from a file",
        prog="appinject",
    )
    parser.add_argument(
        "--total-fault-number", type=int, help="total fault number", required=True
    )
    parser.add_argument(
        "--range-file", help="Description file of app memory map", required=True
    )

    parsed = parse_args_safely(parser, args)
    if parsed is None:
        return

    path = parsed.range_file
    try:
        count = int(parsed.total_fault_number)
        if count <= 0:
            raise ValueError
    except ValueError:
        print("Invalid count")
        return

    addresses = parse_address_ranges_file(path)
    if len(addresses) == 0:
        print("No valid addresses found in file.")
        return
    if count > len(addresses):
        print(
            f"Requested {count} injections, but only {len(addresses)} addresses found."
        )
        return

    print(
        f"Performing {count} bitflip injections from {len(addresses)} available addresses..."
    )
    targets = random.sample(addresses, count)
    for address in targets:
        try:
            inject_bitflip(address, 1)
        except Exception as e:
            print(f"Injection failed at 0x{address:x}: {e}")


@BuildCmd
def send_qemu_serial(args):
    """Send `data` to QEMU serial"""
    parser = argparse.ArgumentParser(
        prog="send_qemu_serial", description="Send data to qemu serial"
    )
    parser.add_argument("--data", help="data sent to qemu serial", required=True)

    parsed = parse_args_safely(parser, args)
    data = parsed.data
    send_to_qemu_serial(data)


@BuildCmd
def rangeinject(args):
    """Inject bitflips within a custom address range with random or sequential injection.
    Supports loading VM snapshot before injection for reproducible testing.
    Allows excluding specific memory ranges from injection.

    Usage: rangeinject --start-address <addr> --end-address <addr> --total-fault-number <num> --min-interval <time> --max-interval <time> [--injection-mode <mode>] [--bytewidth <width>] [--bit-index <bit>] [--snapshot-tag <tag>] [--observe-time <time>] [--exclude-ranges <ranges>]

    Example:
        rangeinject --start-address 0x1000000 --end-address 0x2000000 --total-fault-number 100 --min-interval 10ms --max-interval 50ms --injection-mode random --snapshot-tag my_checkpoint --observe-time 5s
        rangeinject --start-address 0x1000000 --end-address 0x2000000 --total-fault-number 100 --min-interval 10ms --max-interval 50ms --injection-mode sequential --bytewidth 4 --bit-index 3 --snapshot-tag test_state --observe-time 10s
        rangeinject --start-address 0x1000000 --end-address 0x2000000 --total-fault-number 100 --min-interval 10ms --max-interval 50ms --exclude-ranges "0x1500000-0x1600000,0x1800000-0x1900000"

    Parameters:
    - start-address: Starting address of the injection range
    - end-address: Ending address of the injection range
    - total-fault-number: Total number of faults to inject
    - min-interval: Minimum interval between injections (with unit: ns, us, ms, s, m)
    - max-interval: Maximum interval between injections (with unit: ns, us, ms, s, m)
    - injection-mode: "random" (default) or "sequential" injection within the range
    - bytewidth: Byte width for injection (default: 1)
    - bit-index: Specific bit to flip (if not specified, randomly selected)
    - snapshot-tag: VM snapshot to load before injection (optional)
    - observe-time: Time to observe after all injections are completed (with unit: ns, us, ms, s, m, optional)
    - exclude-ranges: Comma-separated list of ranges to exclude (format: "start1-end1,start2-end2", e.g., "0x1500000-0x1600000,0x1800000-0x1900000")
    """
    parser = argparse.ArgumentParser(
        description="Inject bitflips within a custom address range",
        prog="rangeinject",
    )
    parser.add_argument(
        "--start-address",
        required=True,
        help="Starting address of the injection range (hex format, e.g., 0x1000000)",
    )
    parser.add_argument(
        "--end-address",
        required=True,
        help="Ending address of the injection range (hex format, e.g., 0x2000000)",
    )
    parser.add_argument(
        "--total-fault-number",
        type=int,
        required=True,
        help="Total number of faults to inject",
    )
    parser.add_argument(
        "--min-interval",
        required=True,
        help="Minimum interval between injections (with unit: ns, us, ms, s, m)",
    )
    parser.add_argument(
        "--max-interval",
        required=True,
        help="Maximum interval between injections (with unit: ns, us, ms, s, m)",
    )
    parser.add_argument(
        "--injection-mode",
        choices=["random", "sequential"],
        default="random",
        help="Injection mode: random (default) or sequential",
    )
    parser.add_argument(
        "--bytewidth",
        type=int,
        default=1,
        help="Byte width for injection (default: 1)",
    )
    parser.add_argument(
        "--bit-index",
        type=int,
        help="Specific bit index to flip (if not specified, randomly selected)",
    )
    parser.add_argument(
        "--snapshot-tag",
        help="VM snapshot to load before injection (optional)",
    )
    parser.add_argument(
        "--observe-time",
        help="Time to observe after all injections are completed (with unit: ns, us, ms, s, m, optional)",
    )
    parser.add_argument(
        "--exclude-ranges",
        help="Comma-separated list of ranges to exclude (format: 'start1-end1,start2-end2', e.g., '0x1500000-0x1600000,0x1800000-0x1900000')",
    )

    parsed = parse_args_safely(parser, args)
    if parsed is None:
        return

    try:
        # Parse and validate address range
        start_addr = int(parsed.start_address, 16)
        end_addr = int(parsed.end_address, 16)
        if start_addr >= end_addr:
            raise ValueError("Start address must be less than end address")

        # Parse other parameters
        fault_count = parsed.total_fault_number
        assert fault_count >= 1, "Total fault number must be >= 1"

        min_interval = parse_time(parsed.min_interval)
        max_interval = parse_time(parsed.max_interval)
        assert 0 <= min_interval <= max_interval, "min_interval must be <= max_interval"

        bytewidth = parsed.bytewidth
        assert bytewidth >= 1, "Byte width must be >= 1"

        injection_mode = parsed.injection_mode
        bit_index = parsed.bit_index
        snapshot_tag = parsed.snapshot_tag
        observe_time = parsed.observe_time
        exclude_ranges_str = parsed.exclude_ranges

        # Parse exclude ranges if specified
        exclude_ranges = []
        if exclude_ranges_str:
            try:
                for range_str in exclude_ranges_str.split(","):
                    range_str = range_str.strip()
                    if "-" in range_str:
                        start_str, end_str = range_str.split("-", 1)
                        exclude_start = int(start_str.strip(), 16)
                        exclude_end = int(end_str.strip(), 16)
                        if exclude_start >= exclude_end:
                            raise ValueError(
                                f"Invalid exclude range: {range_str} (start >= end)"
                            )
                        exclude_ranges.append((exclude_start, exclude_end))
                    else:
                        raise ValueError(f"Invalid exclude range format: {range_str}")
                print(f"Excluding {len(exclude_ranges)} memory ranges from injection")
                for start, end in exclude_ranges:
                    print(f"  Exclude: 0x{start:x} - 0x{end:x}")
            except ValueError as e:
                print(f"Error parsing exclude ranges: {e}")
                return

        # Parse observe time if specified
        if observe_time:
            observe_ns = parse_time(observe_time)
            assert observe_ns >= 0, "Observe time must be >= 0"
        else:
            observe_ns = None

    except (ValueError, AssertionError) as e:
        print("Error: %s" % str(e))
        return

    # Load snapshot if specified
    if snapshot_tag:
        print(f"Loading VM snapshot: {snapshot_tag}")
        try:
            qemu_hmp("loadvm %s" % snapshot_tag)
            print(f"Successfully loaded snapshot: {snapshot_tag}")
        except Exception as e:
            print(f"Failed to load snapshot {snapshot_tag}: {e}")
            return

    print(f"Starting range injection from 0x{start_addr:x} to 0x{end_addr:x}")
    print(
        f"Mode: {injection_mode}, Fault count: {fault_count}, Byte width: {bytewidth}"
    )
    if bit_index is not None:
        print(f"Target bit index: {bit_index}")

    # Generate target addresses based on injection mode
    address_range = end_addr - start_addr
    target_addresses = []

    def is_address_excluded(addr, bytewidth, exclude_ranges):
        """Check if an address range (addr to addr+bytewidth) overlaps with any exclude range"""
        addr_end = addr + bytewidth
        for exclude_start, exclude_end in exclude_ranges:
            # Check if there's any overlap between [addr, addr_end) and [exclude_start, exclude_end)
            if addr < exclude_end and addr_end > exclude_start:
                return True
        return False

    if injection_mode == "random":
        # Random injection: generate random addresses within the range, avoiding excluded areas
        attempts = 0
        max_attempts = fault_count * 100  # Prevent infinite loop

        while len(target_addresses) < fault_count and attempts < max_attempts:
            addr = start_addr + random.randint(0, address_range - bytewidth)
            if not is_address_excluded(addr, bytewidth, exclude_ranges):
                target_addresses.append(addr)
            attempts += 1

        if len(target_addresses) < fault_count:
            print(
                f"Warning: Could only generate {len(target_addresses)} valid addresses out of {fault_count} requested (excluded ranges may be too large)"
            )
    else:  # sequential
        # Sequential injection: divide range evenly, skipping excluded areas
        if fault_count > address_range // bytewidth:
            print(
                f"Warning: Fault count ({fault_count}) exceeds available addresses in range"
            )
            fault_count = address_range // bytewidth

        step_size = max(1, address_range // fault_count)
        for i in range(fault_count):
            addr = start_addr + (i * step_size)
            if addr + bytewidth <= end_addr:
                if not is_address_excluded(addr, bytewidth, exclude_ranges):
                    target_addresses.append(addr)
                else:
                    # Try to find next valid address
                    for offset in range(1, step_size):
                        next_addr = addr + offset
                        if next_addr + bytewidth <= end_addr:
                            if not is_address_excluded(
                                next_addr, bytewidth, exclude_ranges
                            ):
                                target_addresses.append(next_addr)
                                break
            else:
                break

    print(
        f"Generated {len(target_addresses)} valid target addresses (excluded {len(exclude_ranges)} ranges)"
    )

    # Perform injections
    stime = time.time()
    successful_injections = 0

    for i, address in enumerate(target_addresses):
        try:
            # Wait for random interval
            if min_interval < max_interval:
                wait_time = random.randint(min_interval, max_interval)
            else:
                wait_time = min_interval

            if wait_time > 0:
                step_ns(wait_time)

            # Determine bit to flip
            if bit_index is not None:
                bit_to_flip = bit_index
            else:
                bit_to_flip = random.randint(0, bytewidth * 8 - 1)

            # Inject bitflip
            inject_bitflip(address, bytewidth, bit_to_flip)
            successful_injections += 1

            print(
                f"Injection {i + 1}/{len(target_addresses)}: 0x{address:x}, bit {bit_to_flip}"
            )

        except Exception as e:
            print(f"Injection failed at 0x{address:x}: {e}")

    etime = time.time()
    duration = etime - stime
    print(
        f"Range injection completed: {successful_injections}/{len(target_addresses)} successful"
    )
    print(f"Total injection duration: {duration:.3f} s")

    # Observe VM for specified time if requested
    if observe_ns is not None:
        print(f"Observing VM for {observe_time}")
        observe_start = time.time()
        step_ns(observe_ns)
        observe_end = time.time()
        observe_duration = observe_end - observe_start
        print(f"Observation completed. Observed for {observe_duration:.3f} s")


def categorize_aarch64_registers():
    """
    将 AArch64 寄存器分为通用寄存器和控制寄存器两类

    Returns:
        tuple: (general_registers, control_registers)
            general_registers: 通用寄存器列表，包括 x0-x30, pc, sp, cpsr, fpsr, fpcr
            control_registers: 控制寄存器列表，包括除通用寄存器之外的所有寄存器
    """
    # 定义 AArch64 通用寄存器
    general_register_patterns = [
        # x0-x30 通用寄存器
        r"^x([0-9]|[12][0-9]|30)$",
        # 程序计数器
        r"^pc$",
        # 栈指针
        r"^sp$",
        # 程序状态寄存器
        r"^cpsr$",
        # 浮点状态寄存器
        r"^fpsr$",
        # 浮点控制寄存器
        r"^fpcr$",
    ]

    # 获取所有可用寄存器
    register = Registers()
    all_registers = [r.name for r, nb in register.list_registers()]

    general_registers = []
    control_registers = []

    for reg_name in all_registers:
        is_general = False
        for pattern in general_register_patterns:
            if re.match(pattern, reg_name, re.IGNORECASE):
                general_registers.append(reg_name)
                is_general = True
                break

        if not is_general:
            control_registers.append(reg_name)

    return general_registers, control_registers


def inject_reg_by_category(category, bit=None):
    """
    根据寄存器类别注入错误

    Args:
        category: 'general' 表示通用寄存器，'control' 表示控制寄存器
        bit: 要翻转的位索引，如果为 None 则随机选择
    """
    general_regs, control_regs = categorize_aarch64_registers()

    if category == "general":
        target_registers = general_regs
    elif category == "control":
        target_registers = control_regs
    else:
        print(
            f"Error: Invalid register category '{category}'. Must be 'general' or 'control'."
        )
        return

    if not target_registers:
        print(f"No {category} registers found!")
        return

    # 随机选择一个目标寄存器
    random.shuffle(target_registers)

    for reg in target_registers:
        # 尝试注入直到找到一个可以成功注入的寄存器
        if inject_register_bitflip(reg, bit):
            print(f"Successfully injected fault into {category} register: {reg}")
            break
        print(f"Trying another {category} register...")
    else:
        print(f"Out of {category} registers to try!")
