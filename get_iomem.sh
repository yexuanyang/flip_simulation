#!/bin/bash

# This file should run in qemu machine
parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
cd "$parent_path"
cat /proc/iomem > iomem.txt

