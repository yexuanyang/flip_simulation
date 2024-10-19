# ==============================================================================
# This file describes the utility functions that are used in the main script gdb.py.
# 
# Author: Yexuan Yang <myemailyyxg@gmail.com>
# Date: 2024-10-18
# ==============================================================================

import random
import time
import subprocess

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

def flip_bit_in_area(address_dict, area):
    address_start = int(address_dict[area][0][0], base=16)
    address_end = int(address_dict[area][0][1], base=16)

    random.seed(time.time())
    random_address = random.randint(address_start,address_end+1)
    random_bit = random.randint(0,7)

    command_list = []
    command_list.append(f'x/bx 0x{random_address:x}\n')
    command_list.append(f'set *0x{random_address:x}^=1<<{random_bit}\n')
    command_list.append(f'x/bx 0x{random_address:x}\n')
    with open('gdb_command.txt', 'w') as f:
        f.writelines(command_list)
    subprocess.run(['./gdb.sh'], check=True, stdout=subprocess.DEVNULL)
    print(f'flip the Bit {random_bit} in the Byte at physical address 0x{random_address:x} in area {area}')

def vm_action(action):
    if action in ['save', 'load', 'del']:
        subprocess.run(['./snap.sh', action], check=True, stdout=subprocess.DEVNULL)
        print(f'{action} the snapshot named "tmpsnap"')
    else:
        print('Invalid action')
