#include "atlahs_htsim_api.h"
#include "atlahs_event.h"
#include "datacenter/fat_tree_topology.h"

#include "logsim-interface.h"
#include "lgs/LogGOPSim.hpp"
    
void AtlahsHtsimApi::Send(const SendEvent &event, graph_node_properties elem) {
    //std::cout << "AtlahsHtsimApi: Sending event" << std::endl;


    // New additions
    /* UecSrc::_rss_params                   = {8, timeFromUs(200.), UecSrc::MEAN_RTT, 3, 0, 0, 25};
    UecSrc::_flowbender_params            = {0.05, 1};
    UecSrc::_uss_params                   = {8, 3};
    UecSrc::ecmp_background_traffic_nodes = 0;
    UecSrc::_load_balancing_algo = UecSrc::RSS; */
    int to = event.getTo();
    int from = event.getFrom();
    int tag = event.getTag();
    int size = event.getSizeBytes();
    size = size * 1;    

    simtime_picosec transmission_delay =
            (Packet::data_packet_size() * 8 / speedAsGbps(linkspeed) * _topo->cfg().get_diameter() *
             1000) +
            (UecBasePacket::get_ack_size() * 8 / speedAsGbps(linkspeed) * _topo->cfg().get_diameter() *
             1000);
        simtime_picosec base_rtt_bw_two_points =
            2 * _topo->cfg().get_two_point_diameter_latency(from, to) + transmission_delay;

    

    from = getHtsimNodeNumber(from, elem.nic);
    to = getHtsimNodeNumber(to, elem.nic);

    simtime_picosec flow_duration = size * 8 / 200 * 1000;

    if (from == to) {
        std::cerr << "Error: Send event from and to the same node" << std::endl;
        exit(0);
    }

    // [CC-DIAG] record same-pair overlap (uses the htsim node numbers + tag that
    // EventOver will carry, so EventFinished can match this entry on completion).
    {
        auto key = std::make_pair(from, to);
        auto &tags = _cc_inflight[key];
        _cc_total++;
        _cc_pairs.insert(key);
        if (!tags.empty()) {
            _cc_overlap++;
            if (tags.count(tag) > 0) _cc_overlap_sametag++;
        }
        tags.insert(tag);
        if (tags.size() > _cc_max_concurrent) _cc_max_concurrent = tags.size();
        if (_cc_total % 50000 == 0) {
            printf("[CC-DIAG] sends=%lu distinct_pairs=%zu max_concurrent_pair=%lu "
                   "overlap=%lu (sametag=%lu difftag=%lu)\n",
                   (unsigned long)_cc_total, _cc_pairs.size(),
                   (unsigned long)_cc_max_concurrent, (unsigned long)_cc_overlap,
                   (unsigned long)_cc_overlap_sametag,
                   (unsigned long)(_cc_overlap - _cc_overlap_sametag));
            fflush(stdout);
        }
    }

    if (_logsim_interface->get_protocol() == UEC_PROTOCOL) {
        TrafficLoggerSimple* traffic_logger = NULL;

        // GOAL replay creates one short-lived flow per send (millions total), so enable
        // flow teardown: free each (src,sink) pair once it is fully quiescent (stage 2:
        // detection only). Harmless to set every call; off for fixed-flow drivers.
        UecSrc::_free_completed_flows = true;

        // Construct a fresh multipath instance per flow
        if (!mp_factory) {
            std::cerr << "Error: Multipath not set in AtlahsHtsimApi" << std::endl;
            exit(0);
        }
        auto per_flow_mp = mp_factory();

        UecSrc *uecSrc = new UecSrc(traffic_logger, *_eventlist, std::move(per_flow_mp), *uec_nics.at(from), 1);

        // setFlowsize is the correct method name
        uecSrc->setFlowsize(size);
        uecSrc->initNscc(cwnd_b, base_rtt_bw_two_points);


        uecSrc->setName("uec_" + std::to_string(from) + "_" + std::to_string(to));
        uecSrc->from = from;
        uecSrc->to = to;
        uecSrc->tag = tag;
        uecSrc->send_size = size;
        uecSrc->_atlahs_api = this;

        UecSink *uecSink = new UecSink(traffic_logger,
                                  linkspeed,
                                  1.1,
                                  UecBasePacket::unquantize(UecSink::_credit_per_pull),
                                  *_eventlist,
                                  *uec_nics.at(to),
                                  1);
        uecSink->setName("uec_sink_Rand");
        uecSink->from_sink = from;
        uecSink->to_sink = to;
        uecSink->tag_sink = tag;

        uecSrc->set_dst(to);
        uecSrc->setSrc(from);
        uecSrc->setDst(to);
        uecSink->set_src(from);

        Route* srctotor = new Route();
        srctotor->push_back(_topo->queues_ns_nlp[from][_topo->cfg().HOST_POD_SWITCH(from)][0]);
        srctotor->push_back(_topo->pipes_ns_nlp[from][_topo->cfg().HOST_POD_SWITCH(from)][0]);
        srctotor->push_back(_topo->queues_ns_nlp[from][_topo->cfg().HOST_POD_SWITCH(from)][0]->getRemoteEndpoint());

        Route* dsttotor = new Route();
        dsttotor->push_back(_topo->queues_ns_nlp[to][_topo->cfg().HOST_POD_SWITCH(to)][0]);
        dsttotor->push_back(_topo->pipes_ns_nlp[to][_topo->cfg().HOST_POD_SWITCH(to)][0]);
        dsttotor->push_back(_topo->queues_ns_nlp[to][_topo->cfg().HOST_POD_SWITCH(to)][0]->getRemoteEndpoint());

        // Stash the per-flow routes on the src so they can be freed at teardown (stage 3);
        // they are only referenced by this flow's ports, so the driver owns their lifetime.
        uecSrc->_fwd_route = srctotor;
        uecSrc->_rev_route = dsttotor;

        graph_node_properties* node_copy = new graph_node_properties(elem);
        uecSrc->lgs_node = node_copy;
        //uecSrc->connect(srctotor, dsttotor, *uecSink, _eventlist->now());

        uecSrc->connectPort(0, *srctotor, *dsttotor, *uecSink, _eventlist->now());

        //register src and snk to receive packets from their respective TORs. 
        assert(_topo->switches_lp[_topo->cfg().HOST_POD_SWITCH(from)]);
        assert(_topo->switches_lp[_topo->cfg().HOST_POD_SWITCH(from)]);
        _topo->switches_lp[_topo->cfg().HOST_POD_SWITCH(from)]->addHostPort(
                        from, uecSink->flowId(), uecSrc->getPort(0));
        _topo->switches_lp[_topo->cfg().HOST_POD_SWITCH(to)]->addHostPort(
                        to, uecSrc->flowId(), uecSink->getPort(0));

    }
    // TODO: Move this stuff to a CreateConnection function inside UEC. 
    // TODO: Support different tranports, not just UEC
}

void AtlahsHtsimApi::Recv(const RecvEvent &event) {
    // No Op for HTSIM
}

void AtlahsHtsimApi::Calc(const ComputeAtlahsEvent &event) {
    // Done Directly in lgs_interface for now
}

void AtlahsHtsimApi::Setup() {
    printf("No of nodes %d\n", total_nodes);

    if (_logsim_interface->get_protocol() == EQDS_PROTOCOL) {
        /* for (size_t ix = 0; ix < total_nodes; ix++){
            printf("Setting up node %d\n", ix);
            pacersEQDS.push_back(new EqdsPullPacer(linkspeed, 0.99, EqdsSrc::_mtu, *_eventlist));   
            nics.push_back(new EqdsNIC(*_eventlist, linkspeed));
        } */
    } else if (_logsim_interface->get_protocol() == NDP_PROTOCOL) {
        /* for (size_t ix = 0; ix < total_nodes; ix++)
            pacersNDP.push_back(new NdpPullPacer(*_eventlist,  linkspeed, 0.99));    */
    }


    for (size_t ix = 0; ix < total_nodes; ix++) {
        uec_pacers.push_back(new UecPullPacer(linkspeed,
                                          0.99,
                                          UecBasePacket::unquantize(UecSink::_credit_per_pull),
                                          *_eventlist,
                                          1));

        UecNIC* nic = new UecNIC(ix, *_eventlist, linkspeed, 1);
        uec_nics.push_back(nic);
    }
    
}

void AtlahsHtsimApi::EventFinished(const EventOver &event) {
    //std::cout << "AtlahsHtsimApi: Event is over" << std::endl;

    if (AtlahsEventType::SEND_EVENT_OVER == event.getEventType()) {
        // [CC-DIAG] this send finished -> remove one entry for its (from,to)+tag.
        {
            auto it = _cc_inflight.find(std::make_pair(event.getFrom(), event.getTo()));
            if (it != _cc_inflight.end()) {
                auto t = it->second.find(event.getTag());
                if (t != it->second.end()) it->second.erase(t);
            }
        }
        //_logsim_interface->flow_over(*(event.getPacket()));
        _logsim_interface->flow_over(event);
    } else if (AtlahsEventType::COMPUTE_EVENT_OVER == event.getEventType()) {
        _logsim_interface->compute_over(1);
    } else {
        abort();
    }
}

// STAGE 3: queue a quiescent flow for deferred teardown. Called from
// UecSrc::maybeTeardown(), which can run mid packet-free, so we ONLY enqueue here --
// never delete inline (that would be a use-after-free of the in-progress flow).
void AtlahsHtsimApi::scheduleFlowFree(UecSrc* src) {
    _pending_free.push_back(src);
}

// STAGE 3: actually free the flows queued by scheduleFlowFree(). MUST be called from a
// safe (non-packet-processing) context -- the LGS driver loop -- so no packet handler is
// on the stack referencing these objects. By construction each flow here is quiescent
// (done, both refcounts 0, no RTO, not NIC-queued), so nothing in the network, eventlist
// or NIC still points at it; we additionally drop its switch host-routes first so any
// straggler misses the FIB and is dropped (stage 1) instead of touching freed memory.
void AtlahsHtsimApi::drainPendingFree() {
    if (_pending_free.empty())
        return;
    static uint64_t flows_freed = 0;
    for (UecSrc* src : _pending_free) {
        UecSink* sink = src->sink();
        int from = src->from;
        int to = src->to;
        // Mirror the two addHostPort() calls in Send() (DATA carries src flowid -> sink
        // port at `to`; ACK carries sink flowid -> src port at `from`).
        _topo->switches_lp[_topo->cfg().HOST_POD_SWITCH(from)]->removeHostPort(from, sink->flowId());
        _topo->switches_lp[_topo->cfg().HOST_POD_SWITCH(to)]->removeHostPort(to, src->flowId());
        // Free everything Send() allocated for this flow.
        delete sink;
        delete src->_fwd_route;
        delete src->_rev_route;
        delete src->lgs_node;
        delete src;
        if (++flows_freed % 50000 == 0) {
            std::cout << "[FLOW-FREED] " << flows_freed << std::endl;
            std::cout.flush();
        }
    }
    _pending_free.clear();
}
