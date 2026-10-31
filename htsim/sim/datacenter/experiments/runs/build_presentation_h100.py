#!/usr/bin/env python3
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
import os
try:
    from PIL import Image
    def dims(p):
        w,h=Image.open(p).size; return w/h
except Exception:
    def dims(p): return 2.6

RUNS=os.path.dirname(os.path.abspath(__file__))
G=os.path.join(RUNS,"fidelityRuns","graphs")
OUT=os.path.join(RUNS,"IB_vs_UET_presentation_H100.pptx")
def g(name): return os.path.join(G,name)

DARK=RGBColor(0x1F,0x38,0x64); IBC=RGBColor(0x00,0x72,0xB2); UETC=RGBColor(0xD5,0x5E,0x00)
INK=RGBColor(0x22,0x22,0x22); GREY=RGBColor(0x55,0x55,0x55); WHITE=RGBColor(0xFF,0xFF,0xFF)
LIGHT=RGBColor(0xEE,0xF1,0xF7); RAILC=RGBColor(0x00,0x9E,0x73)

prs=Presentation(); prs.slide_width=Inches(13.333); prs.slide_height=Inches(7.5)
SW,SH=prs.slide_width,prs.slide_height
BLANK=prs.slide_layouts[6]

def slide(): return prs.slides.add_slide(BLANK)
def rect(s,l,t,w,h,color):
    sh=s.shapes.add_shape(1,l,t,w,h); sh.fill.solid(); sh.fill.fore_color.rgb=color
    sh.line.fill.background(); return sh
def tb(s,l,t,w,h,anchor=MSO_ANCHOR.TOP):
    b=s.shapes.add_textbox(l,t,w,h); b.text_frame.word_wrap=True; b.text_frame.vertical_anchor=anchor
    return b.text_frame
def para(tf,text,size=18,color=INK,bold=False,bullet=False,level=0,space=6,align=PP_ALIGN.LEFT,italic=False):
    p=tf.paragraphs[0] if (len(tf.paragraphs)==1 and not tf.paragraphs[0].runs) else tf.add_paragraph()
    p.level=level; p.alignment=align; p.space_after=Pt(space)
    r=p.add_run(); r.text=("• " if bullet else "")+text
    r.font.size=Pt(size); r.font.color.rgb=color; r.font.bold=bold; r.font.italic=italic
    r.font.name="Calibri"; return p

def header(s,title,accent=DARK):
    rect(s,0,0,SW,Inches(1.05),accent)
    tf=tb(s,Inches(0.5),Inches(0.12),Inches(12.3),Inches(0.8),MSO_ANCHOR.MIDDLE)
    para(tf,title,size=26,color=WHITE,bold=True)

def content(title,bullets,accent=DARK,sub=None):
    s=slide(); header(s,title,accent)
    top=Inches(1.35)
    if sub:
        tf=tb(s,Inches(0.6),Inches(1.15),Inches(12),Inches(0.5)); para(tf,sub,size=15,color=GREY,italic=True); top=Inches(1.7)
    tf=tb(s,Inches(0.7),top,Inches(12),Inches(5.6))
    for b in bullets:
        if isinstance(b,tuple): txt,lvl=b
        else: txt,lvl=b,0
        para(tf,txt,size=(19 if lvl==0 else 16),color=(INK if lvl==0 else GREY),
             bold=(lvl==0 and txt.endswith(":")),bullet=True,level=lvl,space=(8 if lvl==0 else 3))
    return s

def imageslide(title,img,takeaway,accent=DARK,imgw=12.0):
    s=slide(); header(s,title,accent)
    ar=dims(img); w=Inches(imgw); h=Emu(int(w/ar))
    maxh=Inches(5.05)
    if h>maxh: h=maxh; w=Emu(int(h*ar))
    left=Emu(int((SW-w)/2)); top=Inches(1.25)
    s.shapes.add_picture(img,left,top,width=w,height=h)
    ty=top+h+Inches(0.12)
    bar=rect(s,Inches(0.6),ty,Inches(12.13),Inches(0.72),LIGHT); bar.line.fill.background()
    tf=tb(s,Inches(0.8),ty+Inches(0.04),Inches(11.7),Inches(0.64),MSO_ANCHOR.MIDDLE)
    para(tf,"Takeaway: "+takeaway,size=14.5,color=DARK,bold=False)
    return s

def two_images(title,imgL,imgR,capL,capR,accent=DARK):
    s=slide(); header(s,title,accent)
    for img,cap,lx in [(imgL,capL,0.4),(imgR,capR,6.87)]:
        ar=dims(img); w=Inches(6.0); h=Emu(int(w/ar))
        if h>Inches(4.9): h=Inches(4.9); w=Emu(int(h*ar))
        s.shapes.add_picture(img,Inches(lx),Inches(1.45),width=w,height=h)
        tf=tb(s,Inches(lx),Inches(6.5),Inches(6.0),Inches(0.7)); para(tf,cap,size=13,color=GREY,align=PP_ALIGN.CENTER)
    return s

def section(title,subtitle=None,accent=DARK):
    s=slide(); rect(s,0,0,SW,SH,accent)
    tf=tb(s,Inches(1),Inches(2.9),Inches(11.3),Inches(1.4),MSO_ANCHOR.MIDDLE)
    para(tf,title,size=40,color=WHITE,bold=True,align=PP_ALIGN.CENTER)
    if subtitle:
        tf2=tb(s,Inches(1.5),Inches(4.3),Inches(10.3),Inches(1)); para(tf2,subtitle,size=18,color=RGBColor(0xCF,0xD8,0xEA),align=PP_ALIGN.CENTER)
    return s

import json
N=json.load(open(os.path.join(RUNS,"fidelityRuns","results","deck_numbers.json")))
SEEDC=RGBColor(0x88,0x22,0x55)   # accent for the five-seed section

def stacked_images(title,imgs,takeaway,accent=DARK):
    """Two wide figures stacked full-width, then a takeaway bar."""
    s=slide(); header(s,title,accent)
    top=Inches(1.2); avail=Inches(5.0)
    hs=[]
    for img in imgs:
        ar=dims(img); w=Inches(12.1); h=Emu(int(w/ar)); hs.append((img,ar,w,h))
    tot=sum(h for *_,h in hs)
    scale=min(1.0, avail/tot) if tot else 1.0
    y=top
    for img,ar,w,h in hs:
        h2=Emu(int(h*scale)); w2=Emu(int(h2*ar)); left=Emu(int((SW-w2)/2))
        s.shapes.add_picture(img,left,y,width=w2,height=h2); y=Emu(int(y+h2+Inches(0.05)))
    bar=rect(s,Inches(0.6),Inches(6.45),Inches(12.13),Inches(0.72),LIGHT); bar.line.fill.background()
    tf=tb(s,Inches(0.8),Inches(6.49),Inches(11.7),Inches(0.64),MSO_ANCHOR.MIDDLE)
    para(tf,"Takeaway: "+takeaway,size=14.5,color=DARK)
    return s

def stats(title,cards,note=None,accent=DARK,sub=None):
    """Big-number callouts: cards = [(big, label, color), ...] (up to 4)."""
    s=slide(); header(s,title,accent)
    top=Inches(1.5)
    if sub:
        tf=tb(s,Inches(0.6),Inches(1.2),Inches(12.1),Inches(0.6)); para(tf,sub,size=16,color=GREY,italic=True); top=Inches(1.95)
    n=len(cards); gap=Inches(0.3); w=Emu(int((Inches(12.13)-gap*(n-1))/n)); h=Inches(2.55)
    for i,(big,label,col) in enumerate(cards):
        l=Emu(int(Inches(0.6)+i*(w+gap)))
        box=rect(s,l,top,w,h,LIGHT)
        tf=tb(s,l+Inches(0.2),top+Inches(0.2),w-Inches(0.4),Inches(1.25),MSO_ANCHOR.MIDDLE)
        para(tf,big,size=44,color=col,bold=True,align=PP_ALIGN.CENTER)
        tf=tb(s,l+Inches(0.2),top+Inches(1.45),w-Inches(0.4),Inches(1.0))
        para(tf,label,size=14,color=INK,align=PP_ALIGN.CENTER)
    if note:
        tf=tb(s,Inches(0.7),top+h+Inches(0.35),Inches(12),Inches(2.2))
        for t in (note if isinstance(note,list) else [note]):
            para(tf,t,size=16,color=INK,bullet=True,space=8)
    return s

fr=N["flat_ratio"]; cv=N["cv"]; fl=N["flips"]; sn=N["seeds_needed"]

# ---------------- 1. Title ----------------
s=slide(); rect(s,0,0,SW,SH,DARK); rect(s,0,Inches(4.55),SW,Inches(0.08),IBC)
tf=tb(s,Inches(0.9),Inches(2.0),Inches(11.5),Inches(2.2),MSO_ANCHOR.MIDDLE)
para(tf,"Lossless vs Lossy Datacenter Transports",size=40,color=WHITE,bold=True)
para(tf,"IB (RoCE + DCQCN)  vs  Ultra Ethernet (UEC)  —  flat fabrics and rail-optimized GPU clusters",size=21,color=RGBColor(0xCF,0xD8,0xEA),space=4)
tf2=tb(s,Inches(0.95),Inches(4.8),Inches(11),Inches(1.5))
para(tf2,"DGX H100-class cluster: 400 Gbps fabric + NVLink4.  Every configuration run with five random seeds, reported as mean ± 95% confidence interval.",size=15,color=RGBColor(0x9F,0xB2,0xD0),italic=True)

# ---------------- 2. Motivation ----------------
content("Motivation",[
 "AI / HPC datacenters are bottlenecked by the network, not compute: distributed training and storage are dominated by collective communication (incast, all-to-all, all-reduce).",
 "These patterns create extreme, bursty congestion — many senders hitting one link at once — which a naïve fabric handles badly (drops, retransmissions, collapse).",
 "Two competing industry philosophies for the fabric:",
 ("InfiniBand-style / RoCE: keep the fabric LOSSLESS (PFC back-pressure) and add DCQCN congestion control to slow senders before buffers overflow.",1),
 ("Ultra Ethernet (UEC): let the fabric DROP, but spray each packet across all paths and retransmit fast — tolerate loss instead of preventing it.",1),
 "Question: which wins, on which workloads, and what does each pay for its performance?",
 "Approach: build BOTH stacks in the htsim packet simulator and measure them under identical conditions — repeated across random seeds, so every difference can be tested for significance.",
])

# ---------------- 3. Two stacks ----------------
content("The two stacks",[
 "IB — RoCE transport + DCQCN + lossless PFC fabric:",
 ("Per-flow ECMP (one path per flow, in-order delivery).",1),
 ("PFC pauses upstream when a switch buffer fills → no packet loss.",1),
 ("DCQCN: switches mark packets (ECN) as queues build; senders cut rate on the signal.",1),
 "UET — UEC transport (NSCC congestion control) + lossy fabric:",
 ("Per-packet spray across ALL paths → uses full bisection bandwidth.",1),
 ("Packet trimming: overflowing packets are dropped (payload trimmed) and NACK'd → fast retransmit.",1),
 ("Reorder-tolerant receiver (spray causes heavy reordering).",1),
 "Both simulated in htsim on the SAME topology and workloads → a controlled, apples-to-apples comparison.",
])

# ---------------- 4. Setup ----------------
content("Experimental setup — matched on both sides",[
 "DGX H100-class: 400 Gbps on every fabric tier; NVLink4 at 3600 Gbps (450 GB/s per direction) inside each server.",
 "Flat fabric: 3-tier fat-tree, 128 and 1024 nodes, oversubscription 1:1 / 4:1 / 8:1. Flows of 16, 64, 100 MB. Identical traffic matrices for both stacks.",
 "Five seeds per configuration. The seed sets each switch's ECMP hash salt and path permutation — each seed is a different, equally valid draw of how traffic lands on paths.",
 f"{N['runs_ok']:,} completed runs over {N['cells']} configurations. Mean ± t-based 95% CI; differences tested with Welch's t-test.",
 "Outside the compute/memory budget: all-to-all and ring at 1024 nodes; UET random incast at 1024 / 8:1; UET ring at 64 and 100 MB.",
 "MTU 4000 (IB) vs 4150 (UET) — each stack's native default; the only intentional difference besides the transport.",
], sub="Everything held constant except the transport — and every configuration repeated five times.")

# ---------------- 5-6. Workloads ----------------
content("Workloads we ran — and what they mimic  (1/2)",[
 "Permutation — random & full-bisection:  each node sends to one other node.",
 ("Mimics uniform shuffle / general point-to-point traffic; full-bisection maximally stresses the network core.",1),
 "Incast (random) — many senders → one receiver (all-to-one):",
 ("The classic datacenter pain point: distributed-storage reads, MapReduce shuffle-to-reducer, parameter-server gather, partition/aggregate fan-in.",1),
 "Incast (remote) — incast where senders are the far half of the fabric:",
 ("Same fan-in but forced across the core → stresses incast AND core bandwidth together.",1),
 "Outcast-incast — combined fan-out then fan-in:",
 ("Scatter-then-gather / tree-reduction communication.",1),
], accent=UETC)
content("Workloads we ran — and what they mimic  (2/2)",[
 "All-to-all (concurrent) — every node sends to every other node, all pairs at once:",
 ("A generic all-to-all stress test (MPI_Alltoall, embedding shuffles, FFT transposes, distributed sort). Sizes are PER PAIR — 16 MB means 2 GB sent per node.",1),
 ("Mixture-of-Experts traffic is modelled separately, by the rail-aware MoE all-to-all in Part 2, which uses realistic per-GPU volumes.",1),
 "Ring all-reduce — ring-structured gradient aggregation:",
 ("The dominant collective in data-parallel training (gradient sync every step). Trigger-chained: each step waits for the previous one.",1),
 "Oversubscription (1:1 → 8:1) tests each stack as the network core gets more contended.",
 "Together these span the traffic that limits AI/HPC clusters — from benign permutation to pathological all-to-one incast.",
], accent=UETC)

# ---------------- 7. What we measure ----------------
content("What we measure",[
 "Common (directly comparable between stacks):",
 ("Makespan — time for the whole workload to complete (the bottom line).",1),
 ("Flow-completion time (FCT), slowdown = FCT ÷ ideal (tail latency), and per-flow Jain fairness.",1),
 ("Per-tier link utilization (how well each fabric uses the network).",1),
 "Each stack's native congestion signal:",
 ("UET: packet-trim / NACK rate and retransmission count (its cost of dropping).",1),
 ("IB: PFC pause count & pause time, peak buffer occupancy, lossless-overflow check (its cost of back-pressure).",1),
 "New with five seeds: the seed-to-seed spread of every metric — how much a single run can be trusted.",
 "Caveat: for trigger-chained workloads (ring and rail-aware collectives) a flow's FCT includes waiting for its trigger, so slowdown there is relative, not absolute.",
])

# ================= UET RESULTS =================
section("Results — UET (Ultra Ethernet)","Lossy fabric, per-packet spray + trimming, NSCC",UETC)
imageslide("UET — makespan vs oversubscription (128 nodes)",g("f01_uet_makespan_os_128.png"),
 "Permutation finishes fast because spray uses every path; all-to-all and incast dominate. Error bars are barely visible — UET results hardly move between seeds.",UETC)
imageslide("UET — makespan vs oversubscription (1024 nodes)",g("f01_uet_makespan_os_1024.png"),
 "Incast and outcast are flat in oversubscription: the receiver port, not the core, is the bottleneck. Only permutation feels the thinned core.",UETC)
imageslide("UET — congestion: packet-trim rate",g("f02_uet_trim_rate_os_128.png"),
 "All-to-all trims 31% of transmissions at 4:1 and 62% at 8:1, independent of flow size. At 1024 nodes, random incast trims 75–84% — most packets are sent more than once.",UETC)
imageslide("UET — per-tier link utilization (128 nodes, 100 MB)",g("f06_uet_util_heatmap_128.png"),
 "Spray drives links to 0.75–1.00 utilization wherever there is traffic to carry — UET extracts close to the full bandwidth of the fabric.",UETC)

# ================= IB RESULTS =================
section("Results — IB (RoCE + DCQCN)","Lossless PFC fabric, per-flow ECMP, DCQCN",IBC)
imageslide("IB — makespan vs oversubscription (128 nodes)",g("f01_ib_makespan_os_128.png"),
 "Incast is flat in oversubscription (receiver-bound); permutation and all-to-all grow with it because IB pins each flow to one path. Note the wider error bars on permutation.",IBC)
imageslide("IB — makespan vs oversubscription (1024 nodes)",g("f01_ib_makespan_os_1024.png"),
 "Same structure at scale — and IB completes the 1024-node random incast at 8:1 as well.",IBC)
stacked_images("IB — PFC back-pressure, 128 and 1024 nodes",[g("f03_ib_pfc_pause_os_128.png"),g("f03_ib_pfc_pause_os_1024.png")],
 "128 nodes: all-to-all reaches ~246 port-seconds of pause at 8:1. 1024 nodes: random incast reaches ~3,350 port-seconds — back-pressure is IB's price.",IBC)
imageslide("IB — per-tier link utilization (128 nodes, 100 MB)",g("f06_ib_util_heatmap_128.png"),
 "DCQCN paces senders and each flow uses one path: at 1:1 permutation runs links at ~0.2 where UET reaches ~0.87. Bandwidth traded for gentleness.",IBC)
imageslide("IB — peak lossless buffer occupancy",g("f04_ib_peak_buffer_os_128.png"),
 f"PFC holds the peak buffer at ~0.16–0.17 MB for every workload — and zero lossless overflow in all 660 IB runs: the lossless guarantee held everywhere.",IBC)

# ================= ANALYSIS =================
section("Analysis — putting them side by side")
imageslide("IB vs UET on the flat fabric — every cell tested",g("f07_ib_uet_ratio_flat.png"),
 f"All {fr['n']} comparisons are statistically significant. UET is faster in {fr['uet_faster']}; IB wins only {fr['ib_faster']} — all of them incast at 1024 nodes.",DARK)
stats("Analysis (1): speed",[
 ("3.3×","median IB ÷ UET on permutation (range 1.9–8.5×)",UETC),
 ("1.3×","median IB ÷ UET on incast and outcast",UETC),
 ("2.0×","median IB ÷ UET on ring all-reduce",UETC),
 ("3–7%","IB's win: random incast, 1024 nodes (0.5% on remote)",IBC)],
 note=["Why UET wins permutation: it sprays every packet across all paths and saturates the fabric; IB pins each flow to one ECMP path (RoCE needs near-in-order delivery), so flows collide.",
       "Why IB wins the big incast: the receiver port is the physical bottleneck, so spray cannot help — and IB avoids UET's retransmission overhead there."])
imageslide("Fairness and tail slowdown — both stacks",g("f05_fairness_slowdown_both_stacks.png"),
 "Under 8:1 all-to-all UET's fairness collapses to 0.04 — a few flows finish, most wait — while IB's PFC keeps it at 1.0. Tail slowdown is similar (~1000×) on both.",DARK)
content("Analysis (2): the cost of speed",[
 "The two stacks pay for congestion in opposite currencies:",
 ("UET burns BANDWIDTH on retransmission: 62% of transmissions trimmed on all-to-all at 8:1; 75–84% on 1024-node random incast.",1),
 ("IB burns TIME on back-pressure: zero retransmits and zero lossless overflow, but up to ~3,350 port-seconds of PFC pause on 1024-node random incast.",1),
 "Fairness mirrors this. UET's drop-and-retransmit lets some flows race ahead — all-to-all fairness 0.04 at 8:1. IB's back-pressure throttles everyone equally — 1.0.",
 "Utilization mirrors it too: UET runs links near saturation (0.75–1.00); IB deliberately runs them cooler (DCQCN pacing, one path per flow).",
 "So UET is the faster transport almost everywhere — but it is faster by spending bandwidth, and it is unfair under heavy contention.",
])

# ================= PART 2: RAIL =================
section("Part 2 — Rail-Optimized Clusters + NVLink","Modelling how AI clusters are actually built",RAILC)
content("Why rail-optimized? (the real hardware)",[
 "Everything so far assumed a FLAT fabric: every GPU is just an endpoint on a fat-tree. Real AI clusters are not built that way.",
 "A DGX H100 server holds 8 GPUs joined internally by NVLink4/NVSwitch — 450 GB/s per GPU per direction, 9× a 400G NIC.",
 "Each GPU also has its OWN 400G NIC, and each of those NICs is wired to a DIFFERENT switch — its 'rail'. 8 GPUs per server => 8 rails.",
 "So a leaf switch does NOT hold whole servers: it holds ONE GPU from each of many servers — that is what makes it a rail.",
 "Consequence: two GPUs on the same rail are one hop apart; two GPUs in the same server are NOT (different rails) — but they have NVLink between them.",
 "Purpose: make collective traffic either stay inside the server (NVLink, very fast) or stay inside a rail (one leaf, no spine).",
], accent=RAILC)
content("The topology we built (1024 and 2048 GPUs)",[
 "128 servers × 8 GPUs = 1024 GPUs, and the 2048-GPU version (256 servers). Each GPU has its own 400G NIC on its own rail.",
 "8 rails; each rail served by leaf switches of 32 servers each; 64-port leaves (32 down + 32 up); 2-tier leaf-spine, fully NON-BLOCKING.",
 "Host->leaf mapping (this is the whole difference):",
 ("GPU g  ->  rail r = g mod 8,  server s = g / 8,  leaf = r·(leaves per rail) + s / 32",1),
 ("Hosts are attached STRIDED, not consecutively: a leaf holds GPU r of 32 different servers.",1),
 "Control topology: identical shape (same leaves, spines, speeds) but CONSECUTIVE attachment — any difference is attributable to the rail assignment alone.",
 "A second topology models the NVLink domain: one 3600 Gbps crossbar per server, 100 ns links.",
], accent=RAILC)
content("How NVLink is modelled — and why rails need it",[
 "A GPU has TWO attachments: NVLink to its 7 server-mates, and a rail NIC to everything else. A fat-tree gives each host only one, so we run two topologies.",
 "The choice is made per FLOW at connect time: same server -> NVLink plane at 3600 Gbps; otherwise -> rail fabric at 400 Gbps.",
 "Both the link capacity AND the host's send rate must be set per plane — a mismatch silently throttles to the slower one. The simulator now refuses to start if they disagree.",
 "Why rails and NVLink come as a pair: rails deliberately scatter a server's 8 GPUs across 8 leaves.",
 ("Without NVLink, the hierarchical all-reduce's intra-server phases must cross the spine: 64% of its flows cross a spine on the rail mapping, versus 36% on the flat one.",1),
 ("NVLink removes those flows from the fabric entirely; rails then keep the remaining same-rail traffic on one leaf.",1),
], accent=RAILC)
content("The workloads: rail-AWARE collectives",[
 "A rail fabric only pays off if the collective is written for it. Rail-agnostic collectives send 7/8 of their traffic across rails and just pay the cost.",
 "Rail-aware all-reduce (hierarchical, as used on DGX):",
 ("1. intra-server reduce-scatter over NVLink  2. rail-local all-reduce (recursive halving/doubling)  3. intra-server all-gather over NVLink",1),
 "Rail-aware all-to-all = the MoE dispatch pattern (Mixture-of-Experts routing):",
 ("1. NVLink shuffle so data for rail r sits on the GPU at rail r   2. rail-local all-to-all",1),
 ("Per-GPU volume (16–100 MB total) with ~125 KB per peer — the realistic MoE regime. Trades ~1.87× more bytes for locality; the extra bytes ride NVLink.",1),
 "No flow ever crosses rails. Same-rail peers more than 32 servers apart still cross a spine — a rail spans several leaves.",
], accent=RAILC)
stats("The rail sweep: 240 runs, all clean",[
 ("48","configurations: 2 workloads × 2 scales × 3 sizes × {rail, flat} × {IB, UET}",RAILC),
 ("× 5","seeds each — 240 runs, every flow completed",RAILC),
 ("0","lossless overflow on every IB run: the lossless guarantee held",IBC)],
 note=["NVLink is enabled in ALL of them, so rail-vs-flat isolates the host->leaf assignment alone.",
       "The 2048-GPU MoE runs needed a large-memory machine (tens of GB each)."],accent=RAILC)
imageslide("Rail results — makespan vs the shape-matched control",g("f08_rail_vs_flat.png"),
 "Same switch layout in both; only the host->leaf assignment differs. Rails are faster for IB in every configuration, and for UET in nearly every one.",RAILC)
imageslide("How much do rails buy?",g("f09_rail_benefit.png"),
 "IB gains 8–41% (12/12 significant). UET gains 3–10% (10/12 significant; the two exceptions are within noise). Rails are not only an IB optimization.",RAILC)
imageslide("IB vs UET on the rail + NVLink cluster",g("f11_rail_ib_uet_ratio.png"),
 "On all-reduce UET keeps a 1.7–5.4× lead. On MoE the gap is small, and rails shrink it further: at 1024 / 64 MB on rails the two are statistically tied (1.02×, p = 0.18).",RAILC)
imageslide("What each stack pays on the rail fabric",g("f10_rail_congestion_cost.png"),
 "Doubling GPUs 1024 -> 2048 at 100 MB multiplies IB's pause time 4.7× (7.2 -> 33.7 port-s) and UET's retransmits 3.3× (7.5 M -> 25 M). All-reduce costs almost nothing on either.",RAILC)
content("Analysis — rail findings",[
 "1. Rails help BOTH transports, and every IB gain is significant.",
 ("IB: −8% to −41% makespan, 12 of 12 significant; the largest gains are on MoE (−41% at 1024 / 16 MB, −33% at 2048 / 64 MB).",1),
 ("UET: −3% to −10%, 10 of 12 significant. Smaller than IB — spray already avoids hot paths — but real.",1),
 "2. Rails help IB more because they relieve its back-pressure: IB's PFC pause time falls 25–59% on rails, on every MoE configuration.",
 "3. For UET the mechanism is mixed: rails cut retransmits 11–19% in three of the four 64–100 MB cells, but leave them within ±4% in the other three. Part of UET's MoE cost is set at the receiving endpoint, which no topology change relieves.",
 "4. On MoE, rails bring the two stacks close: IB/UET is 1.02–1.33× on rails versus 1.21–1.86× on the flat control.",
 "5. Congestion cost grows super-linearly with scale: 2× the GPUs gives 4.7× IB pause time and 3.3× UET retransmits (MoE, 100 MB).",
], accent=RAILC)

# ================= PART 3: FIVE SEEDS =================
section("Part 3 — What five seeds tell us","How much of a single simulation run is luck?",SEEDC)
stats("The seed matters — for one transport",[
 (f"{cv['ib']['max']:.0f}%","largest seed-to-seed CV of IB makespan (permutation)",IBC),
 (f"{cv['ib']['median']:.1f}%","median IB CV across all configurations",IBC),
 (f"{cv['uet']['median']:.2f}%","median UET CV — nearly deterministic",UETC),
 (f"{cv['uet']['max']:.1f}%","largest UET CV anywhere",UETC)],
 sub="Same topology, same traffic; only the ECMP hash salt and path permutation change between seeds.",
 note=["IB pins each flow to one path, so the seed decides which flows collide. UET sprays every packet across 128 paths, so the collisions average out.",
       "The effect is concentrated where path choice matters: permutation. Incast is decided at the receiver port, regardless of path."],accent=SEEDC)
imageslide("Seed sensitivity by workload",g("f12_seed_cv_by_workload.png"),
 "IB permutation varies up to 17% from seed to seed (median 10%). Incast, all-to-all and ring barely move on either stack.",SEEDC)
imageslide("The single-seed lottery",g("f13_single_seed_spread.png"),
 "On the most seed-sensitive IB configurations, five seeds span 32–42% of the mean. A single run could report any value on the bar. The worst UET case spans 9%.",SEEDC)
imageslide("Does one seed give the wrong answer?",g("f16_single_seed_error.png"),
 f"The DIRECTION is robust: {sum(f for _,f,_ in fl['rail'])} of {5*fl['rail_total']} rail readings and 0 of {5*fl['stack_total']} IB-vs-UET readings flip. The SIZE is not: one seed misreports the rail benefit by up to {fl['rail_err_max']:.0f} points.",SEEDC)
imageslide("Which metrics can you trust from one run?",g("f15_metric_stability.png"),
 "On IB permutation, makespan, p99 FCT and slowdown vary 7–11% and PFC pause time up to 7%; peak buffer is steady. On UET nearly everything stays below 2%.",SEEDC)
imageslide("How many seeds would be enough?",g("f14_seeds_needed.png"),
 f"For ±5% on the worst IB permutation configuration you need ~{sn['IB perm_fullbis']['e5']} seeds (±2%: ~{sn['IB perm_fullbis']['e2']}). Five seeds are enough for incast, all-to-all and ring — and for almost all of UET.",SEEDC)
content("What five seeds changed",[
 "Every headline comparison in this deck is now a tested one:",
 (f"IB vs UET: {fr['n']} of {fr['n']} flat-fabric comparisons significant, 23 of 24 on the rail cluster.",1),
 ("Rail benefit: 22 of 24 significant. The two that are not are UET-only and within ±4% of zero.",1),
 "A single seed would have got the right ORDER almost everywhere — but the wrong SIZE by up to 9 points on the rail benefit and up to 27% on the IB/UET gap.",
 "The uncertainty is transport-specific: IB permutation needs 30–50 seeds for ±5% precision; UET needs 2–6. Any single-seed comparison of the two inherits IB's noise.",
 "Recommendation for simulation studies of per-flow ECMP transports: report seed variance, and budget seeds by workload — permutation traffic needs far more than incast.",
], accent=SEEDC)

# ================= CONCLUSIONS =================
content("Conclusions",[
 "Flat fabric: UET is faster on 90 of 99 configurations — a median 3.3× on permutation, ~1.3× on incast and outcast, 2× on ring all-reduce.",
 ("It wins by spending bandwidth: up to 62–84% of transmissions trimmed and retransmitted, and fairness that collapses (0.04) under heavy all-to-all.",1),
 ("IB wins only where the receiver port is the bottleneck — incast at 1024 nodes, by 3–7% on random incast and 0.5% on remote — and it never drops a packet or overflows a lossless buffer.",1),
 "Rail-optimized + NVLink: rails help both transports — IB by 8–41%, UET by 3–10% — because they cut spine traffic and, for IB, back-pressure.",
 ("On MoE all-to-all, rails bring IB within 2–33% of UET; at 1024 GPUs / 64 MB the two are statistically tied.",1),
 ("Congestion cost scales super-linearly: doubling the GPUs costs IB 4.7× the pause time and UET 3.3× the retransmits.",1),
 "Methodology: IB results carry up to 17% seed-to-seed noise on permutation, UET under 5%. Orderings survive a single seed; effect sizes do not. Multi-seed evaluation is necessary for per-flow ECMP transports.",
], accent=DARK)
content("Future work",[
 "Close the gaps in this sweep: UET ring all-reduce at 64 and 100 MB (needs more than 10 GB per run), and all-to-all / ring at 1024 nodes.",
 "More seeds for IB permutation (30–50 for ±5%) — the one area where five seeds leave wide confidence intervals.",
 "Per-hop latency is 1 µs in all topologies — higher than current switches (~150–450 ns). Latency-bound phases (small-chunk all-reduce steps) are the most sensitive to it.",
 "Tune DCQCN (ECN threshold K, minimum rate) — K = 8 was one operating point, never swept.",
 "Adaptive routing for IB would give it some path diversity — likely closing part of the permutation gap and reducing its seed sensitivity.",
 "Instrument per-receiver backlog directly, to confirm where UET's MoE loss is generated.",
 "Skewed MoE routing (hot experts) — the current MoE all-to-all is uniform.",
 "Real AI communication traces (GOAL / ATLAHS) instead of synthetic collectives.",
], accent=DARK)

s=slide(); rect(s,0,0,SW,SH,DARK)
tf=tb(s,Inches(1),Inches(3.1),Inches(11.3),Inches(1.3),MSO_ANCHOR.MIDDLE)
para(tf,"Thank you",size=40,color=WHITE,bold=True,align=PP_ALIGN.CENTER)
para(tf,"IB (RoCE/DCQCN) vs Ultra Ethernet — a controlled, multi-seed comparison in htsim",size=18,color=RGBColor(0xCF,0xD8,0xEA),align=PP_ALIGN.CENTER)

prs.save(OUT)
print("wrote",OUT,"—",len(prs.slides._sldIdLst),"slides")
