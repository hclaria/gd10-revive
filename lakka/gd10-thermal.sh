#!/bin/sh
# Software thermal throttle for the GD10 (S905) on mainline Linux.
#
# The cpu-thermal zone has no working cooling device here: scpi-cpufreq does not
# register one, and no map covers the Mali-450. Left alone the SoC climbs to the
# 110 C critical trip in 5 to 15 minutes and powers off. Every 2 s, cap the CPU
# and GPU according to the temperature.
POLICY=/sys/devices/system/cpu/cpufreq/policy0
GPU=/sys/class/devfreq/d00c0000.gpu
ZONE=/sys/class/thermal/thermal_zone0/temp

set_max() {
  [ -w "$1" ] && [ "$(cat "$1")" != "$2" ] && echo "$2" > "$1"
}

while true; do
  temp=$(cat $ZONE 2>/dev/null || echo 0)
  if [ "$temp" -ge 90000 ]; then
    cpu=500000 gpu=125000000
  elif [ "$temp" -ge 80000 ]; then
    cpu=1000000 gpu=285714285
  else
    cpu=1296000 gpu=500000000
  fi
  # RetroArch's "Performance (Managed)" mode rewrites the CPU limit, hence the loop.
  set_max $POLICY/scaling_max_freq $cpu
  set_max $GPU/max_freq $gpu
  sleep 2
done
