#!/bin/sh
set -eu

if [ "${OFFLINE_NETWORK:-false}" = "true" ]; then
  iptables -w -F OUTPUT
  iptables -w -P OUTPUT DROP
  iptables -w -A OUTPUT -o lo -j ACCEPT
  iptables -w -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
fi

exec gosu studio "$@"
