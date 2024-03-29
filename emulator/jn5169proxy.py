import serial
import struct
import argparse

verbose = False

def dumpMessage(direction, msglen, msgtype, data):
    if not verbose:
        return

    print(direction + " " + "{:02x} {:02x} ".format(msglen, msgtype) + ' '.join('{:02x}'.format(x) for x in data))
    

def transferMsg(direction, src, dst):
    header = src.read(2)
    msglen, msgtype = struct.unpack('BB', header)
    data = src.read(msglen - 1)

    dumpMessage(direction, msglen, msgtype, data)

    dst.write(header)
    dst.write(data)


def main():
    parser = argparse.ArgumentParser(description="Proxy and dump JN5169 flashing messages")
    parser.add_argument("srcport", help="Source serial port (flasher side)")
    parser.add_argument("dstport", help="Destination serial port (device side)")
    parser.add_argument("-v", "--verbose", action='store_true', help="Set verbose mode")
    args = parser.parse_args()
    
    global verbose
    verbose = args.verbose

    print(f"Starting proxy on {args.srcport} and {args.dstport} ports")
    src = serial.Serial(args.srcport, baudrate=38400)
    dst = serial.Serial(args.dstport, baudrate=38400)

    while True:
        transferMsg(">", src, dst)
        transferMsg("<", dst, src)

main()