import gdb
import random
import re

class MemoryRange:
    def __init__(self, start, end, priority, kind, name):
        self.start, self.end, self.priority, self.kind, self.name = start, end, priority, kind, name
        
    @staticmethod
    def parse(line):
        # example:
        # "  0000000000000000-000000000000ffff (prio 0, i/o): io"
        pattern = r'^([0-9a-fA-F]+)-([0-9a-fA-F]+) \(prio (\d+), ([a-zA-z0-9/]+)\): ([\w\.-]+)'
        matches = re.findall(pattern, line.strip())
        assert matches != [], "invalid line: %r" % line
        return MemoryRange(
            start=int(matches[0][0], 16),
            end=int(matches[0][1], 16),
            priority=int(matches[0][2]),
            kind=matches[0][3],
            name=matches[0][4]
        )

class FlatView:
    def __init__(self):
        self.ranges = []

    @staticmethod
    def parse(lines):
        fv = FlatView()
        for line in lines:
            fv.ranges.append(MemoryRange.parse(line))
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

def qemu_hmp(cmdstr):
    return gdb.execute("monitor %s" % cmdstr, to_string=True).strip()

def mtree():
    # TODO: clean up this parser to handle errors more cleanly
    lines = qemu_hmp("info mtree -f").split("\n")
    views = {}
    curnames = None
    scanning = False
    for line in lines:
        line = line.rstrip()
        if line.startswith("FlatView #"):
            curnames = []
            scanning = False
        elif line.startswith(' AS "'):
            assert line.count('"') == 2, "invalid AS line: %r" % line
            assert not scanning, "expected not scanning"
            cn = line.split('"')[1]
            curnames.append(cn)
            views[cn] = []
        elif line.startswith(' Root '):
            assert not scanning, "expected not scanning"
            scanning = True
        elif line.startswith('  No rendered FlatView'):
            assert scanning, "expected scanning"
            for cn in curnames:
                assert views[cn] == [], "views[cn] is not empty"
                del views[cn]
            curnames = None
        elif line.startswith('  '):
            assert scanning and curnames, "invalid state to begin view"
            for name in curnames:
                views[name].append(line)
        else:
            assert not line, "unexpected line: %r" % line

    return {name: FlatView.parse(body) for name, body in views.items()}

cached_reg_list = None

def list_registers():
    global cached_reg_list
    if cached_reg_list is None:
        # we can avoid needing to handle float and 'union neon_q', because on ARM, there are d# registers that alias
        # to all of the more specialized registers in question.
        frame = gdb.selected_frame()
        cached_reg_list = [(r, frame.read_register(r).type.sizeof)
                           for r in frame.architecture().registers()
                           if str(frame.read_register(r).type) not in ("float", "union neon_q", "neon_q")]
    return cached_reg_list[:]

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

    assert nvalue == rnvalue and nvalue != ovalue, \
        "mismatched values: o=0x%x n=0x%x rn=0x%x" % (ovalue, nvalue, rnvalue)
    print("Injected bitflip into address 0x%x: old value 0x%x -> new value 0x%x" % (address, ovalue, nvalue))

def sample_address():
    return mtree()["memory"].random_address()

def inject_register_bitflip(register_name, bit=None):
    value = gdb.selected_frame().read_register(register_name)
    if str(value.type) in ("long", "long long", "void *", "void (*)()"):
        lookup = None
    elif str(value.type) == "union neon_d" or str(value.type) == "neon_d":
        lookup = "u64"
    else:
        raise RuntimeError("not handled: inject_register_bitflip into register %s of type %s"
                           % (register_name, value.type))

    bitcount = 8 * value.type.sizeof
    bitmask = (1 << bitcount) - 1
    if bit is None:
        bit = random.randint(0, bitcount - 1)

    intval = int(value[lookup] if lookup else value)
    newval = intval ^ (1 << bit)
    gdb.execute("set $%s%s = %d" % (register_name, "." + lookup if lookup else "", newval))
    # global_writer.write_other()

    reread = gdb.selected_frame().read_register(register_name)
    rrval = int(reread[lookup] if lookup else reread)
    if (newval & bitmask) == (rrval & bitmask):
        print("Injected bitflip into register %s: old value 0x%x -> new value 0x%x" % (register_name, intval, rrval))
        # log_writer.log_command("inject_reg %s %u" % (register_name, bit))
        return True
    elif (intval & bitmask) == (rrval & bitmask):
        print("Bitflip could not be injected into register %s. (0x%x -> 0x%x ignored.)"
              % (register_name, intval, newval))
        return False
    else:
        raise RuntimeError("double-mismatched register values on register %s: o=0x%x n=0x%x rr=0x%x"
                           % (register_name, intval, newval, rrval))
    
def inject_reg_internal(register_name, bit=None):
    registers = [r.name for r, nb in list_registers()]
    if register_name:
        # Support wildcard input like "r*x"
        regexp = re.compile("^" + ".*".join(re.escape(segment) for segment in register_name.split("*")) + "$")
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

def inject_instant_restart():
    # log_writer.log_command("task_restart")

    # this is a UDF instruction in arm
    gdb.execute("set $pc = 0xE7F000F0")
    # global_writer.write_other()

def now():
    text = qemu_hmp("info vtime")
    assert text.startswith("virtual time: ") and text.endswith(" ns") and text.count(" ") == 3, \
        "invalid output: %r" % text
    return int(text.split(" ")[2])

def step_ns(ns):
    qemu_hmp("cont")
    qemu_hmp("stop_delayed %s" % ns)

time_units = {
    "": 1,
    "ns": 1,
    "us": 1000,
    "ms": 1000 * 1000,
    "s": 1000 * 1000 * 1000,
    "m": 60 * 1000 * 1000 * 1000,
}

def parse_time(s):
    for unit, mul in sorted(time_units.items()):
        if s.endswith(unit):
            try:
                res = int(s[:-len(unit)])
            except ValueError:
                continue  # try the next unit
            if res <= 0:
                raise ValueError("expected positive number of %s in %r" % (unit, s))
            return res * mul
    raise ValueError("could not parse units in %r" % s)

class BuildCmd(gdb.Command):
    def __init__(self, target):
        self.__doc__ = target.__doc__
        super(BuildCmd, self).__init__(
            target.__name__, gdb.COMMAND_USER
        )
        self.target = target

    def complete(self, text, word):
        return gdb.COMPLETE_NONE

    def invoke(self, args, from_tty):
        return self.target(args)

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
    lr = list_registers()
    maxlen = max(len(r.name) for r, nb in lr)
    for register, num_bytes in lr:
        print("  REG:", register.name.rjust(maxlen), "->", num_bytes)

@BuildCmd
def stop_delayed(args):
    """Stop the QEMU instance after a delay of the input nano-seconds."""

    if args.strip() == "":
        print("usage: stop_delayed <ns>")
        print("Create a <ns> nano-seconds delayed VM stop")
        return

    step_ns(args)

@BuildCmd
def inject(args):
    """Inject a bitflip at an address."""

    args = args.strip().split(" ")
    if len(args) > 3:
        print("usage: inject [<address>] [<bytewidth>] [<bit>]")
        print("if no address specified, will be randomly selected, and bytewidth will default to 1")
        print("otherwise, bytewidth defaults to 4 bytes")
        print("bit specifies the bit index within the integer to flip")
        return

    if args and args[0]:
        # Support argument like "inject 0x1234+0x11 4 3"
        address = int(gdb.parse_and_eval(args[0]))
        bytewidth = int(args[1]) if args[1:] else 4
        if bytewidth < 1 or address < 0:
            print("invalid bytewidth or address")
            return
    else:
        address = sample_address()
        bytewidth = 1

    bit = (int(args[2]) if args[2:] else None)

    inject_bitflip(address, bytewidth, bit)

@BuildCmd
def inject_reg(args):
    """Inject a bitflip into a register."""

    args = args.split()
    if len(args) > 2:
        print("usage: inject_reg [<register name>] [<bit index>]")
        print("if no register specified, will be randomly selected")
        print("a pattern involving wildcards can be specified if desired")
        return

    inject_reg_internal(args[0] if args[0:] else None, int(args[1]) if args[1:] else None)

# @BuildCmd
# def task_restart(args):
#     """Inject a UDF instruction to force a task restart."""
#     if args.strip():
#         print("usage: task_restart")
#         return

#     inject_instant_restart()

@BuildCmd
def autoinject(args):
    """
    Automatically inject fault into the VM accroding to the provided inject type. 
    Cause `total_fault_number` faults with a random cycle between `min_interval` and `max_interval`,
    fault type is `fault_type`

    Format: `autoinject <total_fault_number> <min_interval> <max_interval> <fault_type>`
    
    Supported types:
    1. ram: inject fault in RAM
    2. reg: inject fault in Registers
    """
    args = args.strip().split(" ")
    if len(args) != 4 or args[3] not in ("ram", "reg"):
        print("usage: autoinject <total_fault_number> <min_interval> <max_interval> <fault_type>")
        print("Automatically inject faults into the VM accroding to the provided inject type.")
        print("Interval is uniformly random at [min, max].")
        print("unit should be 'ms', 'us', 'ns', 's', 'm'. Default is 'ns'.")
        print("Fault type should be 'ram' or 'reg'")
        return

    times = int(args[0])
    assert times >= 1, "times < 1"
    mint = parse_time(args[1])
    maxt = parse_time(args[2])
    assert 0 < mint <= maxt, "min_interval > max_interval"
    ftype = args[3]

    for _ in range(times):
        step_ns(random.randint(mint, maxt))

        if ftype == "reg":
            inject_reg_internal(None)
        elif ftype == "ram":
            inject_bitflip(sample_address(), 1)