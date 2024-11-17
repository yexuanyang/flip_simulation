# ==============================================================================
# This file describes the utility functions that are used in the main script gdb.py.
# 
# Author: Yexuan Yang <myemailyyxg@gmail.com>
# Date: 2024-10-18
# ==============================================================================

import random
import time
import subprocess
from pygdbmi.gdbcontroller import GdbController

def extract(file) -> dict:
    address_dict = {
        "Kernel Code": [],
        "Kernel Data": [],
        "System RAM": []
    }

    with open(file, 'r') as f:
        address_lines = f.readlines()

        for line in address_lines:
            parts = line.strip().split(':')
            start_address, end_address = parts[0].strip().split('-')
            category = parts[-1].strip()
            
            if category == "Kernel code":
                address_dict["Kernel Code"].append((start_address, end_address))
            elif category == "Kernel data":
                address_dict["Kernel Data"].append((start_address, end_address))
            elif category == "System RAM":
                address_dict["System RAM"].append((start_address, end_address))
    return address_dict

def flip_bit_in_area(address_dict, area, gdbmi):
    address_start = int(address_dict[area][0][0], base=16)
    address_end = int(address_dict[area][0][1], base=16)

    random.seed(time.time())
    random_address = random.randint(address_start,address_end+1)
    random_bit = random.randint(0,7)

    # command_list = []
    # command_list.append(f'x/bx 0x{random_address:x}\n')
    # command_list.append(f'set *0x{random_address:x}^=1<<{random_bit}\n')
    # command_list.append(f'x/bx 0x{random_address:x}\n')
    # with open('gdb_command.txt', 'w') as f:
    #     f.writelines(command_list)
    # subprocess.run(['./gdb.sh'], check=True, stdout=subprocess.DEVNULL)
    # print(f'Inject fault at physical address 0x{random_address:x} in area {area}')

    # attached to qemu gdb server
    commands = ["set logging enable on", "target remote:1234", "maintenance packet Qqemu.PhyMemMode:1"]
    gdbmi.write(commands)

    # 
    # Example:
    #[{'type': 'log', 'message': None, 'payload': 'x/bx 0x40001000\n', 'stream': 'stdout'}, 
    # {'type': 'console', 'message': None, 'payload': '0x40001000:\t0x6d\n', 'stream': 'stdout'}, 
    # {'type': 'result', 'message': 'done', 'payload': None, 'token': None, 'stream': 'stdout'}]
    #
    oldvalue = gdbmi.write(f'x/bx 0x{random_address:x}')[1]['payload'].split(":")[1].strip()
    gdbmi.write(f'set *0x{random_address:x}^=1<<{random_bit}')
    newvalue = gdbmi.write(f'x/bx 0x{random_address:x}')[1]['payload'].split(":")[1].strip()
    gdbmi.write("detach")
    print(f'Inject fault at physical address 0x{random_address:x} in area {area}, old={oldvalue}, new={newvalue}')

def vm_action(action, snapname):
    assert action in ['savevm', 'loadvm', 'delvm'], "vm_action error: Invalid args"
    command_list = []
    command_list.append(f'monitor {action} {snapname}\n')
    with open('gdb_command.txt', 'w') as f:
        f.writelines(command_list)
    subprocess.run(['./gdb.sh'], check=True, stdout=subprocess.DEVNULL)
