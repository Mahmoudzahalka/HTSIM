// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-        
#ifndef _LOSSLESS_INPUT_QUEUE_H
#define _LOSSLESS_INPUT_QUEUE_H
#include "queue.h"
/*
 * A FIFO queue that supports PAUSE frames and lossless operation
 */

#include <list>
#include "config.h"
#include "eventlist.h"
#include "network.h"
#include "loggertypes.h"
#include "eth_pause_packet.h"
#include "switch.h"
#include "callback_pipe.h"

class Switch;

class LosslessInputQueue : public Queue, public VirtualQueue {
public:
    LosslessInputQueue(EventList &eventlist);
    LosslessInputQueue(EventList &eventlist,BaseQueue* peer, Switch* sw, simtime_picosec wire_latency);
    LosslessInputQueue(EventList &eventlist,BaseQueue* peer);

    virtual void receivePacket(Packet& pkt);

    void sendPause(unsigned int wait);
    virtual void completedService(Packet& pkt);

    virtual void setName(const string& name) {
        Logged::setName(name); 
        _nodename += name;
    }
    virtual string& nodename() { return _nodename; }

    enum {PAUSED,READY,PAUSE_RECEIVED};

    static uint64_t _low_threshold;
    static uint64_t _high_threshold;

    // --- IB congestion instrumentation (aggregated across all input queues) ---
    // PFC backpressure fingerprint: how often ports paused, total port-time spent
    // paused, and the high-water buffer occupancy (bytes). Reset per process run.
    static uint64_t _total_pauses;         // number of PAUSE episodes (wait>0)
    static simtime_picosec _total_pause_time; // summed (resume_time - pause_time)
    static mem_b _max_occupancy;           // peak input-queue occupancy seen (bytes)

private:
    int _state_recv;
    CallbackPipe* _wire;
    simtime_picosec _pause_start;          // when this queue last entered PAUSED
};

#endif
