"""Measures UDP loss with numbered packets.

iperf3 keeps a TCP control connection open during a UDP test, and under heavy loss it can hang.
This has no control connection: the sender states how many packets it sent, and the receiver
counts how many distinct ones arrived.
"""
import argparse
import json
import socket
import struct
import time

PACKET_BYTES = 1000
HEADER = struct.Struct("!I")


def longest_gap(seen):
    """Longest run of missing packets. A long run means a stall, not evenly spread loss."""
    ordered = sorted(seen)
    return max((b - a - 1 for a, b in zip(ordered, ordered[1:])), default=0)


def receive(port, idle_seconds):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Room for bursts, so a brief scheduling delay here doesn't look like network loss.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 21)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(idle_seconds)
    seen = set()
    try:
        while True:
            data = sock.recv(2048)
            seen.add(HEADER.unpack_from(data)[0])
    except socket.timeout:
        pass
    print(json.dumps({"received": len(seen), "longest_gap": longest_gap(seen)}))


def send(host, port, packets_per_second, seconds):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    padding = bytes(PACKET_BYTES - HEADER.size)
    total = packets_per_second * seconds
    start = time.monotonic()
    for seq in range(total):
        # Absolute send times, so scheduling delays don't lower the rate.
        delay = start + seq / packets_per_second - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        sock.sendto(HEADER.pack(seq) + padding, (host, port))
    print(json.dumps({"sent": total}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["send", "recv"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5300)
    parser.add_argument("--pps", type=int, default=625)
    parser.add_argument("--seconds", type=int, default=3)
    parser.add_argument("--idle", type=float, default=2.0)
    args = parser.parse_args()
    if args.mode == "recv":
        receive(args.port, args.idle)
    else:
        send(args.host, args.port, args.pps, args.seconds)


if __name__ == "__main__":
    main()
