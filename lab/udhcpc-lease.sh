#!/bin/sh
# busybox udhcpc calls this with the lease in environment variables.
case "$1" in
    bound|renew)
        ip addr flush dev "$interface"
        ip addr add "$ip/$mask" dev "$interface"
        ip route replace default via "$router" dev "$interface"
        printf '{"ip":"%s","mask":"%s","router":"%s","dns":"%s","lease":%s,"server":"%s"}\n' \
            "$ip" "$mask" "$router" "$dns" "$lease" "$serverid" > "$LEASE_FILE"
        ;;
esac
exit 0
