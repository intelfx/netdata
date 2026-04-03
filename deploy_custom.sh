#!/bin/bash

set -eo pipefail
shopt -s lastpipe

. lib.sh

TARGET="$1"
shift ||:
if [[ $TARGET =~ ^([^:]+):(.*)$ ]]; then
  host="${BASH_REMATCH[1]}"
  prefix="${BASH_REMATCH[2]:-/}"
else
  host="root@localhost"
  prefix="${TARGET:-/}"
fi

if [[ $prefix == / ]]; then
  libexecdir=/usr/lib/netdata
else
  libexecdir=/usr/libexec/netdata
fi
libdir=/usr/lib/netdata

declare -A FILES
FILES=(
  [src/collectors/python.d.plugin/python_modules]=PREFIX/LIBEXECDIR/python.d

  # [src/collectors/python.d.plugin/python.d.conf]=PREFIX/LIBDIR/conf.d
  [src/collectors/python.d.plugin/turbostat/turbostat.chart.py]=PREFIX/LIBEXECDIR/python.d
  [src/collectors/python.d.plugin/zfsiostat/zfsiostat.chart.py]=PREFIX/LIBEXECDIR/python.d
  # [src/collectors/python.d.plugin/turbostat/turbostat.conf]=PREFIX/LIBDIR/conf.d/python.d
  # [src/collectors/python.d.plugin/zfsiostat/zfsiostat.conf]=PREFIX/LIBDIR/conf.d/python.d

  [src/collectors/python.d.plugin/python.d.conf]=PREFIX/etc/netdata
  # [src/collectors/python.d.plugin/turbostat/turbostat.chart.py]=/etc/netdata/custom-plugins.d/python.d/
  # [src/collectors/python.d.plugin/zfsiostat/zfsiostat.chart.py]=/etc/netdata/custom-plugins.d/python.d/
  [src/collectors/python.d.plugin/turbostat/turbostat.conf]=PREFIX/etc/netdata/python.d/
  [src/collectors/python.d.plugin/zfsiostat/zfsiostat.conf]=PREFIX/etc/netdata/python.d/
)

ssh_control=(-o ControlPath="deploy-$$")
ssh_control_master=(-o ControlMaster=yes -o ControlPersist=10 "${ssh_control[@]}")
ssh_control_slave=(-o ControlMaster=no "${ssh_control[@]}")

set -x
# mkpipe pipe_rd_fd pipe_wr_fd

# ssh "${ssh_control_master[@]}" "$host" -- cat <&$pipe_rd_fd &
ssh "${ssh_control_master[@]}" -fN "$host"
export RSYNC_RSH="ssh ${ssh_control_slave[*]}"
{ set +x; } &>/dev/null

for src in "${!FILES[@]}"; do
  dest="${FILES["$src"]}"
  dest="${dest/PREFIX/"$prefix"}"
  dest="${dest/LIBDIR/"$libdir"}"
  dest="${dest/LIBEXECDIR/"$libexecdir"}"
  dest="${dest//'//'/'/'}"

  Trace rsync -r --partial --no-i-r -ltDH --chmod=ugo=rwX --checksum --itemize-changes "$@" \
    "$src" "$host:$dest"
done
