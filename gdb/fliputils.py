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