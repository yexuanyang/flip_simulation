# This file should run in Host machine
import subprocess
import random
import time

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

if __name__ == '__main__':
    address_dict = extract('iomem.txt')
    print("current qemu ram mapping is:")
    for k, v in address_dict.items():
        print(f'{k}: [0x{v[0][0]}, 0x{v[0][1]}]')

    area = address_dict.keys()
    flip_time = 0
    """
    Except there will be 10 bits flip occur in 1 GB RAM per month.
    For 5 years and 16 GB RAM machine in space, there will be 5 * 12 * 16 * 10 = 9600 times flip.
    There are 5 * 360 * 24 * 3600 = 155,520,000 seconds in 5 years, so one flip occurs every 155520000 / 9600 = 16200 seconds.
    One bit flip use nearly 0.155s in program, we assume 0.5s in program as 16200s in real world, 
    so program sleep 0.345s after every flip.
    We simulate 8G machine in 5 years, in other word we simulate 4800 times flip. 
    Because every flip takes 0.5s in program so the program will run 40 minutes.
    """
    while flip_time < 4800:
        flip_bit_in_area(address_dict, 'System RAM')
        flip_time += 1
        time.sleep(0.345)
    