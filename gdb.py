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

def filp_bit_in_area(address_dict, area):
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
    print(f'filp the Bit {random_bit} in the Byte at physical address 0x{random_address:x} in area {area}')

if __name__ == '__main__':
    address_dict = extract('iomem.txt')
    print("current qemu ram mapping is:")
    for k, v in address_dict.items():
        print(f'{k}: [0x{v[0][0]}, 0x{v[0][1]}]')

    area = address_dict.keys()
    filp_time = 0
    while filp_time < 0x4000_0000:
        filp_bit_in_area(address_dict, 'System RAM')
        filp_bit_in_area(address_dict, 'Kernel Data')
        filp_time += 1
        time.sleep(0.005)
    
    filp_time = 0
    while filp_time < 0x4000:
        filp_time += 1
        filp_bit_in_area(address_dict, 'Kernel Code')