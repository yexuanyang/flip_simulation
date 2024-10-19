#!/bin/bash
# ========================
# This file get the phy-memory map of the qemu machine
#
# Note: This file should run in qemu machine
#
# Author: Yexuan Yang <myemailyyxg@gmail.com>
# Date: 2024-05-17
# ========================
parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
cd "$parent_path"
cat /proc/iomem > iomem.txt

