# ==============================================================================
# This file describes the utility functions that are used in the main script gdb.py.
# 
# Author: Yexuan Yang <myemailyyxg@gmail.com>
# Date: 2024-10-18
# ==============================================================================

import random
import time
import subprocess
import uuid

from pygdbmi.gdbcontroller import GdbController


def extract(file) -> dict:
    """
    Extract the /proc/iomem file and return a dictionary with the following format:

    {
        "Kernel Code": [(start_address, end_address), ...],
        "Kernel Data": [(start_address, end_address), ...],
        "System RAM": [(start_address, end_address), ...]
    }
    """
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

def flip_bit_in_area(address_dict, area, gdbmi: GdbController=None):
    address_start = int(address_dict[area][0][0], base=16)
    address_end = int(address_dict[area][0][1], base=16)

    random.seed(time.time())
    random_address = random.randint(address_start,address_end+1)
    random_bit = random.randint(0,7)

    if gdbmi:
        # attached to qemu gdb server
        commands = ["set logging enable on", "target remote:1234", "maintenance packet Qqemu.PhyMemMode:1"]
        gdbmi.write(commands)

        # 
        # response example:
        #[{'type': 'log', 'message': None, 'payload': 'x/bx 0x40001000\n', 'stream': 'stdout'}, 
        # {'type': 'console', 'message': None, 'payload': '0x40001000:\t0x6d\n', 'stream': 'stdout'}, 
        # {'type': 'result', 'message': 'done', 'payload': None, 'token': None, 'stream': 'stdout'}]
        #
        oldvalue = gdbmi.write(f'x/bx 0x{random_address:x}')[1]['payload'].split(":")[1].strip()
        gdbmi.write(f'set *0x{random_address:x}^=1<<{random_bit}')
        newvalue = gdbmi.write(f'x/bx 0x{random_address:x}')[1]['payload'].split(":")[1].strip()
        # detach to make qemu running
        gdbmi.write("detach")
        print(f'Inject fault at physical address 0x{random_address:x} in area {area}, old={oldvalue}, new={newvalue}')
    else:
        command_list = []
        command_list.append(f'x/bx 0x{random_address:x}\n')
        command_list.append(f'set *0x{random_address:x}^=1<<{random_bit}\n')
        command_list.append(f'x/bx 0x{random_address:x}\n')
        with open('gdb_command.txt', 'w') as f:
            f.writelines(command_list)
        subprocess.run(['./gdb.sh'], check=True, stdout=subprocess.DEVNULL)
        print(f'Inject fault at physical address 0x{random_address:x} in area {area}')

def vm_action(action, snapname, gdbmi: GdbController=None):
    """Execute savevm, loadvm or delvm command in qemu monitor"""
    assert action in ['savevm', 'loadvm', 'delvm'], "vm_action error: Invalid args"
    if gdbmi:
        commands = ["set logging enable on", "target remote:1234", "maintenance packet Qqemu.PhyMemMode:1",
                    f"monitor {action} {snapname}", "detach"]
        gdbmi.write(commands)
    else:
        command_list = []
        command_list.append(f'monitor {action} {snapname}\n')
        with open('gdb_command.txt', 'w') as f:
            f.writelines(command_list)
        subprocess.run(['./gdb.sh'], check=True, stdout=subprocess.DEVNULL)
    print(f"{action} {snapname}")

def autoinject_ram(fault_number, min_interval, max_interval, area: str = "System RAM", gdbmi: GdbController=None):
    """Automatically inject faults into RAM, interval unit is nanosecond"""
    address_dict = extract('iomem.txt')
    print("current qemu ram mapping is:")
    for k, v in address_dict.items():
        print(f'{k}: [0x{v[0][0]}, 0x{v[0][1]}]')
   
    gdbmi, shouldexit = (GdbController(), True) if gdbmi is None else (gdbmi, False)

    for _ in range(fault_number):
        flip_bit_in_area(address_dict, area, gdbmi)
        time.sleep(random.randint(min_interval, max_interval) * 1e-9)

    if shouldexit:
        gdbmi.exit()

def snapinject_ram(fault_number, min_interval, max_interval, observe_time, loop = 1):
    """
    Record the current VM state, then automatically inject faults according to the user-provided fault count and 
    fault interval. After the faults are injected, wait for a while and then revert to the
    previous VM state. 
    """
    tmpname = uuid.uuid4()
    gdbmi = GdbController()

    vm_action('savevm', tmpname, gdbmi)

    for _ in range(loop):
        autoinject_ram(fault_number, min_interval, max_interval, gdbmi=gdbmi)
        print("Observing the machine for %d seconds" % observe_time)
        time.sleep(observe_time)
        vm_action('loadvm', tmpname, gdbmi)

    vm_action('delvm', tmpname, gdbmi)

    gdbmi.exit()