import random
import re
import socket
import threading

from logger import log_single

import gdb


class MemoryRange:
    def __init__(self, start, end, priority, kind, name):
        self.start, self.end, self.priority, self.kind, self.name = (
            start,
            end,
            priority,
            kind,
            name,
        )

    @staticmethod
    def parse(line):
        """
        Parse a memory range line into a MemoryRange object.

        Args:
            line (str): Memory range line like "  0000000000000000-000000000000ffff (prio 0, i/o): io"

        Returns:
            MemoryRange: Parsed memory range object

        Raises:
            ValueError: If line format is invalid
        """
        # Pattern matches: start-end (prio N, type): name [optional_suffix]
        pattern = (
            r"^\s*([0-9a-fA-F]+)-([0-9a-fA-F]+)\s+\(prio\s+(\d+),\s+([^)]+)\):\s+(\S+)"
        )
        match = re.match(pattern, line.strip())

        if not match:
            raise ValueError(f"Invalid memory range line format: {line!r}")

        try:
            return MemoryRange(
                start=int(match.group(1), 16),
                end=int(match.group(2), 16),
                priority=int(match.group(3)),
                kind=match.group(4).strip(),
                name=match.group(5),
            )
        except (ValueError, IndexError) as e:
            raise ValueError(
                f"Failed to parse memory range values from line {line!r}: {e}"
            )


class FlatView:
    def __init__(self):
        self.ranges = []

    @staticmethod
    def parse(lines):
        """
        Parse memory range lines into a FlatView object.

        Args:
            lines (list): List of memory range lines

        Returns:
            FlatView: Parsed FlatView object
        """
        fv = FlatView()
        for line in lines:
            try:
                fv.ranges.append(MemoryRange.parse(line))
            except ValueError as e:
                print(f"Warning: Skipping invalid memory range line: {e}")
                continue
        return fv

    def ram_ranges(self):
        return [(r.start, r.end) for r in self.ranges if r.kind == "ram"]

    def random_address(self):
        ranges = self.ram_ranges()
        lens = [(end - start) for start, end in ranges]
        offset = random.randint(0, sum(lens) - 1)
        for start, end in ranges:
            offset += start
            if offset < end:
                return offset
            offset -= end
        assert False, "should have been in range!"


class RegistersMeta(type):
    _instances = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)

        return cls._instances[cls]


class Registers(metaclass=RegistersMeta):
    def __init__(self):
        self.cached_reg_list = None

    def list_registers(self):
        if self.cached_reg_list is None:
            # we can avoid needing to handle float and 'union neon_q', because on ARM, there are d# registers that alias
            # to all of the more specialized registers in question.
            frame = gdb.selected_frame()
            self.cached_reg_list = [
                (r, frame.read_register(r).type.sizeof)
                for r in frame.architecture().registers()
                if str(frame.read_register(r).type)
                in ("long", "void *", "void (*)()", "union aarch64v")
            ]
        return self.cached_reg_list[:]


def qemu_hmp(cmdstr):
    return gdb.execute("monitor %s" % cmdstr, to_string=True).strip()


def send_to_qemu_serial(cmdstr: str, socket_address):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(socket_address)
    except Exception as e:
        print(
            f"Warning: send_to_qemu_serial fail, socket address {socket_address}, exception {e}"
        )
        return
    client.sendall(cmdstr.encode())
    client.close()
    return


def mtree():
    """
    Parse QEMU memory tree output and return a dictionary of FlatView objects.

    Returns:
        dict: Mapping of address space names to FlatView objects
    """
    try:
        output = qemu_hmp("info mtree -f")
        return _parse_mtree_output(output)
    except Exception as e:
        raise RuntimeError(f"Failed to parse memory tree: {e}")


def _parse_mtree_output(output):
    """
    Parse the raw mtree output into structured data.

    Args:
        output (str): Raw output from 'monitor info mtree -f'

    Returns:
        dict: Mapping of address space names to FlatView objects
    """
    lines = output.split("\n")
    views = {}

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if line.startswith("FlatView #"):
            i, flatview_views = _parse_flatview_section(lines, i)
            views.update(flatview_views)
        else:
            # Skip empty lines or unexpected content
            if line and not line.isspace():
                print(f"Warning: Unexpected line in mtree output: {line!r}")
            i += 1

    return {name: FlatView.parse(body) for name, body in views.items()}


def _parse_flatview_section(lines, start_index):
    """
    Parse a single FlatView section starting from the given index.

    Args:
        lines (list): All lines from mtree output
        start_index (int): Index of the "FlatView #" line

    Returns:
        tuple: (next_index, dict of address_space_name -> memory_range_lines)
    """
    i = start_index + 1
    address_spaces = []
    views = {}

    # Parse AS (Address Space) lines
    while i < len(lines):
        line = lines[i].rstrip()

        if line.startswith(' AS "'):
            as_name = _extract_address_space_name(line)
            address_spaces.append(as_name)
            views[as_name] = []
        elif line.startswith(" Root "):
            # Found root section, now parse memory ranges
            i += 1
            break
        elif line.startswith("FlatView #"):
            # Hit next FlatView section
            return i, views
        else:
            # Skip other lines in header
            pass
        i += 1

    # Parse memory ranges or handle empty FlatView
    if i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("  No rendered FlatView"):
            # Empty FlatView - remove all address spaces for this view
            for as_name in address_spaces:
                # Avoid double free
                if as_name in views:
                    del views[as_name]
            i += 1
        else:
            # Parse memory range lines
            while i < len(lines):
                line = lines[i].rstrip()

                if line.startswith("  ") and _is_memory_range_line(line):
                    # Memory range line - add to all address spaces in this FlatView
                    for as_name in address_spaces:
                        views[as_name].append(line)
                elif line.startswith("FlatView #") or not line:
                    # Hit next section or end
                    break
                else:
                    # Skip unexpected lines
                    if line and not line.isspace():
                        print(f"Warning: Unexpected line in memory ranges: {line!r}")
                i += 1

    return i, views


def _extract_address_space_name(line):
    """
    Extract address space name from AS line.

    Args:
        line (str): Line like ' AS "memory", root: system'

    Returns:
        str: Address space name

    Raises:
        ValueError: If line format is invalid
    """
    if line.count('"') != 2:
        raise ValueError(f"Invalid AS line format: {line!r}")

    return line.split('"')[1]


def _is_memory_range_line(line):
    """
    Check if a line represents a memory range.

    Args:
        line (str): Line to check

    Returns:
        bool: True if line is a memory range
    """
    # Memory range lines have format: "  start-end (prio N, type): name"
    pattern = r"^\s*[0-9a-fA-F]+-[0-9a-fA-F]+\s+\(prio\s+\d+,\s+[^)]+\):\s+\S+"
    return bool(re.match(pattern, line))


def sample_address():
    return mtree()["memory"].random_address()


def inject_bitflip(address, bytewidth, bit=None):
    assert bytewidth >= 1, "invalid bytewidth: %u" % bytewidth
    if bit is None:
        bit = random.randint(0, bytewidth * 8 - 1)

    inferior = gdb.selected_inferior()
    # endianness doesn't actually matter for this purpose, so always use little-endian
    ovalue = int.from_bytes(inferior.read_memory(address, bytewidth), "little")
    nvalue = ovalue ^ (1 << bit)
    inferior.write_memory(address, int.to_bytes(nvalue, bytewidth, "little"))

    rnvalue = int.from_bytes(inferior.read_memory(address, bytewidth), "little")

    assert nvalue == rnvalue and nvalue != ovalue, (
        "mismatched values: o=0x%x n=0x%x rn=0x%x" % (ovalue, nvalue, rnvalue)
    )
    log_single(hex(address), hex(ovalue), hex(nvalue))


def inject_register_bitflip(register_name, bit=None):
    # flush the register cache and reset frame to avoid read old value.
    gdb.execute("maint flush register-cache")
    gdb.execute("frame 0")
    print("flush register-cache and set frame 0")
    try:
        value = gdb.selected_frame().read_register(register_name)
        print_str = gdb.execute(f"p ${register_name}", to_string=True)
        print(f"print_str: {print_str}")
        print(f"read {register_name} value {value}")
    except Exception as e:
        print(
            "[inject_register_bitflip] get exception when reading register value: ", e
        )
    # union aarch64v have 128 bits, but we can only flip 64 of them
    bitcount = min(8 * value.type.sizeof, 64)
    bitmask = (1 << bitcount) - 1
    print(f"flip bit index {bit}")
    if bit is None:
        bit = random.randint(0, bitcount - 1)

    try:
        if str(value.type) == "union aarch64v":
            # $v register, 128 bits.
            # register $v schema:
            #  {
            #   d = {f = {double, double}, u = {uint64_t, uint64_t}, s = {int64_t, int64_t}},
            #   s = {f = {float, ... 3 times}, u = {uint32_t,... 3 times}, s = {int32_t, ... 3 times}},
            #   h = {u = {unsigned, ... 7 times}, s = {signed, ... 7 times}},
            #   b = {u = {uint8_t, <repeats 15 times>}, s = {int8_t, <repeats 15 times>}},
            #   q = {u = {uint128_t}, s = {int128_t}}
            #  }
            # For example, access registers q0-q31 to get the 128 bits, d0-d31 to get the 64 bits, and so on.

            # random pick upper 64 or lower 64
            index = random.randint(0, 1)
            oldval = int(
                gdb.execute(
                    "p ((int64_t[2])$%s)[%d]" % (register_name, index), to_string=True
                )
                .split("=")[1]
                .strip()
            )
            newval = oldval ^ (1 << bit)
            gdb.execute(
                "set ((int64_t[2])$%s)[%d] = %d" % (register_name, index, newval)
            )
            rrval = int(
                gdb.execute(
                    "p ((int64_t[2])$%s)[%d]" % (register_name, index), to_string=True
                )
                .split("=")[1]
                .strip()
            )
        else:
            # normal register, 64 bits
            # assert value.type.sizeof == 8, (
            #     "invalid general register size: %u" % value.type.sizeof
            # )
            oldval = int(value)
            newval = oldval ^ (1 << bit)
            gdb.execute("set $%s = %d" % (register_name, newval))
            print(f"set ${register_name} = {newval}")
            rrval = int(gdb.selected_frame().read_register(register_name))

        if (newval & bitmask) == (rrval & bitmask):
            log_single(register_name, hex(oldval), hex(rrval))
            return True
        elif (oldval & bitmask) == (rrval & bitmask):
            print(
                "Bitflip could not be injected into register %s. (%s -> %s ignored.)"
                % (register_name, hex(oldval), hex(newval))
            )
            return False
        else:
            raise RuntimeError(
                "double-mismatched register values on register %s: o=%s n=%s rr=%s"
                % (register_name, hex(oldval), hex(newval), hex(rrval))
            )
    except Exception as e:
        print("[inject_register_bitflip] exception: ", e)


def inject_reg_internal(register_name, bit=None):
    register = Registers()
    registers = [r.name for r, nb in register.list_registers()]
    if register_name:
        # Support wildcard input like "r*x"
        regexp = re.compile(
            "^"
            + ".*".join(re.escape(segment) for segment in register_name.split("*"))
            + "$"
        )
        registers = [rname for rname in registers if regexp.match(rname)]
    if not registers:
        print("No registers found!")
        return
    # this is the order to try them in
    random.shuffle(registers)

    for reg in registers:
        # keep retrying until we find a register that we CAN successfully inject into
        if inject_register_bitflip(reg, bit):
            break

        print("Trying another register...")
    else:
        print("Out of registers to try!")


def autoinject_inner(times, mint, maxt, ftype):
    for _ in range(times):
        step_ns(random.randint(mint, maxt))

        if ftype == "reg":
            inject_reg_internal(None)
        elif ftype == "ram":
            inject_bitflip(sample_address(), 1)


def inject_instant_restart():
    # log_writer.log_command("task_restart")

    # this is a UDF instruction in arm
    gdb.execute("set $pc = 0xE7F000F0")
    # global_writer.write_other()


def delayed_interrupt(delay_sec):
    import time

    def sleeper():
        print(f">>> sleeping for {delay_sec} seconds")
        time.sleep(delay_sec)

        def do_interrupt():
            print(">>> interrupting target")
            gdb.execute("interrupt")

        # 在线程中调用 GDB 安全方法
        gdb.post_event(do_interrupt)

    threading.Thread(target=sleeper, daemon=True).start()


def step_ns(ns):
    if ns > 0:
        print(">>> sending continue")
        delayed_interrupt(float(ns) / 1e9)
        gdb.execute("continue")


def parse_time(s):
    time_units = {
        "": 1,
        "ns": 1,
        "us": 1000,
        "ms": 1000 * 1000,
        "s": 1000 * 1000 * 1000,
        "m": 60 * 1000 * 1000 * 1000,
    }
    for unit, mul in sorted(time_units.items()):
        if s.endswith(unit):
            try:
                if len(unit) == 0:
                    res = int(s)
                else:
                    res = int(s[: -len(unit)])
            except ValueError:
                continue  # try the next unit
            if res < 0:
                raise ValueError("expected non-positive number of %s in %r" % (unit, s))
            return res * mul
    raise ValueError("could not parse units in %r" % s)
