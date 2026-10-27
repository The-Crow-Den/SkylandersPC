#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read a bounded timing-probe mailbox snapshot from a separately launched process.

No process attachment, input, clock writes or launch/restart actions. Permission
errors are reported rather than worked around. Raw object pointers are private
research data. Repeated snapshots need a persistent cursor to detect data loss.
"""
import argparse
import json
import os
import struct
import time
from .fps_probe_mod import MAGIC, CAPACITY, RECORD_SIZE, MAILBOX_SIZE


def snapshot(read, address, consumed=0, previous_dropped=0, *, allow_loss=False):
    header=read(address,64)
    if len(header)!=64:
        raise ValueError('timing probe header unavailable')
    magic,version,attempts,reserved,produced,dropped,lock,tail=struct.unpack('<8s7Q',header)
    if magic!=MAGIC or version!=1 or reserved or tail or lock not in (0,1):
        raise ValueError('invalid timing probe mailbox')
    if produced<consumed or produced-consumed>CAPACITY:
        raise ValueError('timing probe ring overrun or cursor reset; interval unusable')
    if dropped!=previous_dropped and not allow_loss:
        raise ValueError('timing probe contention loss; interval unusable')
    records=[]
    for ticket in range(consumed+1,produced+1):
        slot=address+64+((ticket-1)%CAPACITY)*RECORD_SIZE
        raw=read(slot,40)
        if len(raw)!=40:
            raise ValueError('timing probe record unavailable')
        sequence,site,obj,arg,dt_bits,scale_bits=struct.unpack('<4Q2I',raw)
        verify=read(slot,8)
        if sequence!=ticket or verify!=struct.pack('<Q',ticket):
            raise ValueError('timing probe concurrent slot reuse; interval unusable')
        if not 1<=site<=32:
            raise ValueError('invalid timing probe site')
        records.append(dict(sequence=ticket,site=site,object=obj,integer_argument=arg,
                            xmm0_bits=dt_bits,xmm1_bits=scale_bits))
    # Contention occurring while reading invalidates the interval as well.
    end=read(address+40,8)
    final_dropped=struct.unpack('<Q',end)[0] if len(end)==8 else -1
    if final_dropped<dropped or final_dropped<previous_dropped:
        raise ValueError('timing probe dropped counter regressed')
    if final_dropped!=dropped and not allow_loss:
        raise ValueError('timing probe contention changed during snapshot')
    return dict(produced=produced,dropped=final_dropped,
                loss_since_last=final_dropped-previous_dropped,attempts=attempts,records=records,
                diagnostic_only=True,wall_time_ns=time.monotonic_ns())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid',type=int)
    parser.add_argument('mailbox',type=lambda value:int(value,0))
    parser.add_argument('--consumed',type=int,default=0)
    parser.add_argument('--previous-dropped',type=int,default=0)
    args=parser.parse_args()
    if args.pid<=0 or args.mailbox<0 or args.consumed<0 or args.previous_dropped<0:
        parser.error('PID must be positive and cursor/address values nonnegative')
    with open(f'/proc/{args.pid}/mem','rb',buffering=0) as memory:
        result=snapshot(lambda address,size:os.pread(memory.fileno(),size,address),
                        args.mailbox,args.consumed,args.previous_dropped)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
